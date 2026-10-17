"""Stage 4 — Load.

Builds a complete warehouse in a *new* DuckDB file (never the published one):

* raw      ``raw_population``                      original strings, as extracted
* staging  ``dim_*``, ``stg_population``          typed, constrained (PK/FK/CHECK)
* mart     ``mart_*``                              SQL transformations in ``sql/marts``
* ops      ``quality_results``, ``pipeline_runs``, ``warehouse_info``
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from copenhagen_data_lab.config.settings import SQL_DIR
from copenhagen_data_lab.pipeline.extract import RawExtract
from copenhagen_data_lab.pipeline.snapshot import public_tableinfo
from copenhagen_data_lab.pipeline.transform import Transformed
from copenhagen_data_lab.utils.logging import get_logger

log = get_logger(__name__)

DIMENSION_TABLES = ("dim_area", "dim_sex", "dim_marital_status", "dim_age", "dim_period")
MART_TABLES = (
    "mart_population_trends",
    "mart_population_demographics",
    "mart_municipality_comparison",
)

OPS_DDL = """
CREATE TABLE quality_results (
    run_id            VARCHAR NOT NULL,
    check_id          VARCHAR NOT NULL,
    name              VARCHAR NOT NULL,
    stage             VARCHAR NOT NULL,
    severity          VARCHAR NOT NULL CHECK (severity IN ('critical', 'warning')),
    status            VARCHAR NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
    records_tested    BIGINT NOT NULL,
    invalid_records   BIGINT NOT NULL,
    explanation       VARCHAR NOT NULL,
    executed_at_utc   TIMESTAMP NOT NULL,
    PRIMARY KEY (run_id, stage, check_id)
);
CREATE TABLE pipeline_runs (
    run_id             VARCHAR PRIMARY KEY,
    source_mode        VARCHAR NOT NULL,
    status             VARCHAR NOT NULL,
    started_at_utc     TIMESTAMP NOT NULL,
    finished_at_utc    TIMESTAMP,
    duration_s         DOUBLE,
    failed_stage       VARCHAR,
    error_message      VARCHAR,
    records_extracted  BIGINT,
    records_staged     BIGINT,
    checks_passed      INTEGER,
    checks_warned      INTEGER,
    checks_failed      INTEGER,
    snapshot_version   VARCHAR,
    latest_period      VARCHAR,
    published          BOOLEAN NOT NULL,
    stages_json        VARCHAR
);
CREATE TABLE warehouse_info (
    build_id                VARCHAR NOT NULL,
    built_at_utc            TIMESTAMP NOT NULL,
    source_mode             VARCHAR NOT NULL,
    snapshot_version        VARCHAR NOT NULL,
    content_sha256          VARCHAR NOT NULL,
    extraction_run_id       VARCHAR NOT NULL,
    extracted_at_utc        TIMESTAMP NOT NULL,
    provider                VARCHAR NOT NULL,
    table_id                VARCHAR NOT NULL,
    table_title             VARCHAR NOT NULL,
    unit                    VARCHAR NOT NULL,
    source_updated_local    TIMESTAMP NOT NULL,
    first_period            VARCHAR NOT NULL,
    last_period             VARCHAR NOT NULL,
    pipeline_version        VARCHAR NOT NULL,
    transformation_version  VARCHAR NOT NULL,
    manifest_json           VARCHAR NOT NULL,
    tableinfo_json          VARCHAR NOT NULL
);
"""

RUN_COLUMNS = [
    "run_id",
    "source_mode",
    "status",
    "started_at_utc",
    "finished_at_utc",
    "duration_s",
    "failed_stage",
    "error_message",
    "records_extracted",
    "records_staged",
    "checks_passed",
    "checks_warned",
    "checks_failed",
    "snapshot_version",
    "latest_period",
    "published",
    "stages_json",
]


def sql_files(subdir: str) -> list[Path]:
    return sorted((SQL_DIR / subdir).glob("*.sql"))


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    log.debug("Executing SQL", extra={"ctx": {"file": path.name}})
    con.execute(path.read_text(encoding="utf-8"))


def _insert_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    view = f"_df_{table}"
    con.register(view, frame)
    try:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {view}")
    finally:
        con.unregister(view)


def runs_frame(runs: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(runs), columns=RUN_COLUMNS)
    for column in ("started_at_utc", "finished_at_utc"):
        frame[column] = pd.to_datetime(frame[column], utc=True, format="ISO8601").dt.tz_localize(
            None
        )
    frame["published"] = frame["published"].fillna(False).astype(bool)
    return frame.drop_duplicates("run_id", keep="last")


def build_warehouse(
    db_path: Path,
    extract: RawExtract,
    transformed: Transformed,
    quality: pd.DataFrame,
    info: dict[str, Any],
) -> dict[str, int]:
    """Create every table in ``db_path`` (which must not exist). Returns row counts."""
    if db_path.exists():
        raise FileExistsError(f"Refusing to build into existing file {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        raw = extract.records.copy()
        raw.insert(0, "extraction_run_id", extract.extraction_run_id)
        con.register("_df_raw", raw)
        con.execute("CREATE TABLE raw_population AS SELECT * FROM _df_raw")
        con.unregister("_df_raw")

        for path in sql_files("staging"):
            run_sql_file(con, path)
        for table in DIMENSION_TABLES:
            _insert_frame(con, table, getattr(transformed, table))
        _insert_frame(con, "stg_population", transformed.stg_population)

        for path in sql_files("marts"):
            run_sql_file(con, path)

        con.execute(OPS_DDL)
        _insert_frame(con, "quality_results", quality)
        info_row = {
            **info,
            "manifest_json": json.dumps(info["manifest_json"], ensure_ascii=False),
            "tableinfo_json": json.dumps(
                public_tableinfo(extract.table_info_raw), ensure_ascii=False
            ),
        }
        _insert_frame(con, "warehouse_info", pd.DataFrame([info_row]))

        counts = {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("raw_population", *DIMENSION_TABLES, "stg_population", *MART_TABLES)
        }
    finally:
        con.close()
    log.info("Warehouse built", extra={"ctx": {"path": str(db_path), **counts}})
    return counts


def append_quality_results(db_path: Path, quality: pd.DataFrame) -> None:
    con = duckdb.connect(str(db_path))
    try:
        _insert_frame(con, "quality_results", quality)
    finally:
        con.close()


def write_runs(db_path: Path, runs: pd.DataFrame) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DELETE FROM pipeline_runs")
        _insert_frame(con, "pipeline_runs", runs)
    finally:
        con.close()
