"""Validate the published DuckDB warehouse (used by CI after the pipeline runs).

    python scripts/check_warehouse.py [--data-dir data]

Exits non-zero if a required table is missing or empty, any quality check failed, the
latest recorded run did not succeed, or the warehouse was not built from the committed
snapshot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.snapshot import read_manifest

REQUIRED = [
    "raw_population",
    "stg_population",
    "dim_area",
    "dim_period",
    "dim_age",
    "dim_sex",
    "dim_marital_status",
    "mart_population_trends",
    "mart_population_demographics",
    "mart_municipality_comparison",
    "quality_results",
    "pipeline_runs",
    "warehouse_info",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env(**({"data_dir": args.data_dir} if args.data_dir else {}))
    problems: list[str] = []

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
        for table in REQUIRED:
            if table not in tables:
                problems.append(f"missing table {table}")
                continue
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<32} {n:>9,} rows")
            if n == 0:
                problems.append(f"empty table {table}")
        failed = con.execute(
            "SELECT check_id, name FROM quality_results WHERE status = 'fail'"
        ).fetchall()
        problems += [f"quality check failed: {c} {n}" for c, n in failed]
        latest = con.execute(
            "SELECT run_id, status FROM pipeline_runs ORDER BY started_at_utc DESC LIMIT 1"
        ).fetchone()
        if latest is None or latest[1] != "success":
            problems.append(f"latest run not successful: {latest}")
        built_from, last_period = con.execute(
            "SELECT content_sha256, last_period FROM warehouse_info"
        ).fetchone()
        manifest = read_manifest(settings.snapshot_dir)
        if built_from != manifest["content_sha256"]:
            problems.append("warehouse was not built from the committed snapshot")
        copenhagen = con.execute(
            """SELECT population FROM mart_population_trends t JOIN dim_area a USING (area_code)
               JOIN dim_period p USING (period_code) WHERE a.is_primary AND p.is_latest"""
        ).fetchone()
        print(f"  latest period {last_period}; primary-area population {copenhagen[0]:,}")
    finally:
        con.close()

    if problems:
        print("WAREHOUSE CHECK FAILED", *problems, sep="\n  - ", file=sys.stderr)
        return 1
    print("Warehouse check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
