"""SQL transformations on known synthetic inputs, checked against hand calculations."""

from __future__ import annotations

import copy
from pathlib import Path

import duckdb
import pytest

from copenhagen_data_lab.pipeline.load import build_warehouse
from copenhagen_data_lab.pipeline.transform import transform
from copenhagen_data_lab.pipeline.verify import verify_warehouse
from copenhagen_data_lab.quality.checks import run_raw_checks
from copenhagen_data_lab.quality.report import to_frame
from fixtures import synthetic


def build(extract, settings, tmp_path: Path) -> Path:
    transformed = transform(extract, settings)
    db = tmp_path / "w.duckdb"
    manifest = {"snapshot_version": "test", "content_sha256": "0" * 64}
    info = {
        "build_id": "b",
        "built_at_utc": "2026-01-01",
        "source_mode": "api",
        "snapshot_version": "test",
        "content_sha256": "0" * 64,
        "extraction_run_id": "x",
        "extracted_at_utc": "2026-01-01",
        "provider": "test",
        "table_id": "FOLK1A",
        "table_title": "t",
        "unit": "Number",
        "source_updated_local": "2026-01-01",
        "first_period": "2022K1",
        "last_period": "2024K4",
        "pipeline_version": "t",
        "transformation_version": "t",
        "manifest_json": manifest,
    }
    build_warehouse(
        db, extract, transformed, to_frame(run_raw_checks(extract, settings), "b"), info
    )
    return db


def total(area: str, period: str) -> int:
    return synthetic.cube()[(area, "TOT", "IALT", "TOT", period)]


@pytest.fixture
def db(synthetic_extract, settings, tmp_path) -> Path:
    return build(synthetic_extract, settings, tmp_path)


def q(db: Path, sql: str, params=None):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def test_yoy_growth_matches_hand_calculation(db):
    ((growth, change, prev_code),) = q(
        db,
        """
        SELECT yoy_growth_pct, yoy_change, yoy_comparison_period_code
        FROM mart_population_trends WHERE area_code = '101' AND period_code = '2024K1'""",
    )
    expected = (total("101", "2024K1") / total("101", "2023K1") - 1) * 100
    assert prev_code == "2023K1"
    assert growth == pytest.approx(expected, abs=1e-12)
    assert change == total("101", "2024K1") - total("101", "2023K1")


def test_first_year_has_no_growth(db):
    rows = q(
        db,
        """SELECT period_code, yoy_growth_pct FROM mart_population_trends
                    WHERE area_code = '101' AND period_index < 2023 * 4 ORDER BY period_index""",
    )
    assert [r[1] for r in rows] == [None, None, None, None]


def test_share_of_denmark_uses_same_period_denominator(db):
    ((share, dk),) = q(
        db,
        """SELECT share_of_denmark_pct, denmark_population
                            FROM mart_population_trends
                            WHERE area_code = '751' AND period_code = '2023K3'""",
    )
    assert dk == total("000", "2023K3")
    assert share == pytest.approx(100 * total("751", "2023K3") / total("000", "2023K3"))
    ((country_share,),) = q(
        db,
        """SELECT share_of_denmark_pct FROM mart_population_trends
                                 WHERE area_code = '000' AND period_code = '2023K3'""",
    )
    assert country_share is None  # Denmark is not expressed as a share of itself


def test_missing_quarter_gives_null_growth_not_wrong_comparison(
    synthetic_extract, settings, tmp_path
):
    """Drop 2023K2 everywhere: 2024K2 must have NULL growth, and 2023K3 must still compare
    with 2022K3 (a naive LAG(4) would pick 2022K2)."""
    gappy = copy.copy(synthetic_extract)
    gappy.records = synthetic_extract.records[synthetic_extract.records["TID"] != "2023K2"]
    gappy.selection = copy.copy(synthetic_extract.selection)
    object.__setattr__(
        gappy.selection,
        "period_codes",
        [p for p in synthetic_extract.selection.period_codes if p != "2023K2"],
    )
    db = build(gappy, settings, tmp_path)
    rows = dict(
        q(
            db,
            """SELECT period_code, yoy_comparison_period_code
                         FROM mart_population_trends WHERE area_code = '101'""",
        )
    )
    assert rows["2024K2"] is None
    assert rows["2023K3"] == "2022K3"


def test_age_groups_never_double_count_totals(db):
    rows = q(
        db,
        """SELECT age_group, population, share_pct, age_total_population
                    FROM mart_population_demographics
                    WHERE area_code = '101' AND period_code = '2024K4' AND sex_code = 'TOT'
                    ORDER BY age_group_order""",
    )
    cube = synthetic.cube()
    singles = {"0–17": ["0", "1"], "18–29": ["20"], "30–44": ["35"], "45–64": ["50"], "65+": ["70"]}
    for group, population, _share, official_total in rows:
        assert population == sum(cube[("101", "TOT", a, "TOT", "2024K4")] for a in singles[group])
        assert official_total == total("101", "2024K4")
    assert sum(r[1] for r in rows) == total("101", "2024K4")
    assert sum(r[2] for r in rows) == pytest.approx(100.0)


def test_age_group_is_null_when_a_single_year_is_missing(synthetic_extract, settings, tmp_path):
    marked = copy.copy(synthetic_extract)
    marked.records = synthetic_extract.records.copy()
    r = marked.records
    r.loc[
        (r["OMRÅDE"] == "101") & (r["KØN"] == "TOT") & (r["ALDER"] == "1") & (r["TID"] == "2024K4"),
        "INDHOLD",
    ] = ".."
    db = build(marked, settings, tmp_path)
    ((pop, missing),) = q(
        db,
        """SELECT population, missing_cells FROM mart_population_demographics
                               WHERE area_code = '101' AND period_code = '2024K4'
                                 AND sex_code = 'TOT' AND age_group = '0–17'""",
    )
    assert pop is None and missing == 1


def test_ranks_only_among_municipalities(db):
    rows = q(
        db,
        """SELECT area_code, area_level, rank_population, municipality_count
                    FROM mart_municipality_comparison WHERE period_code = '2024K4'""",
    )
    levels = {r[0]: r for r in rows}
    assert levels["000"][2] is None  # the country is never ranked
    assert "411" not in levels and "084" not in levels  # special areas/regions excluded
    assert {r[3] for r in rows if r[1] == "municipality"} == {6}
    ranks = sorted(r[2] for r in rows if r[1] == "municipality")
    assert ranks == [1, 2, 3, 4, 5, 6]


def test_constraints_reject_bad_rows(db):
    con = duckdb.connect(str(db))
    try:
        with pytest.raises(duckdb.ConstraintException):
            con.execute("""INSERT INTO stg_population VALUES
                ('101','TOT','IALT','TOT','2024K4', 1, 'reported', '1', 'x')""")  # duplicate PK
        with pytest.raises(duckdb.ConstraintException):
            con.execute("""INSERT INTO stg_population VALUES
                ('999','TOT','IALT','TOT','2024K4', 1, 'reported', '1', 'x')""")  # unknown area
        with pytest.raises(duckdb.ConstraintException):
            con.execute("""INSERT INTO stg_population VALUES
                ('706','TOT','0','U','2024K4', NULL, 'reported', '..', 'x')""")  # NULL as reported
    finally:
        con.close()


def test_post_load_verification_passes(synthetic_extract, settings, db):
    results = verify_warehouse(db, synthetic_extract, transform(synthetic_extract, settings))
    assert {r.status for r in results} == {"pass"}, [r for r in results if r.status != "pass"]
