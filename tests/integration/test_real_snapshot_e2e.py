"""End-to-end on the committed REAL snapshot (Statistics Denmark FOLK1A), fully offline.

Expected values are not hard-coded: they are re-derived from the raw snapshot records with
plain Pandas and compared with what the warehouse and the dashboard queries return.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.database import queries
from copenhagen_data_lab.pipeline.periods import parse_period
from copenhagen_data_lab.pipeline.run import run_pipeline


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Settings, pd.DataFrame]:
    from conftest import BUNDLED_SNAPSHOT

    if not (BUNDLED_SNAPSHOT / "manifest.json").exists():
        pytest.skip("Bundled snapshot not present")
    import shutil

    data = tmp_path_factory.mktemp("real") / "data"
    shutil.copytree(BUNDLED_SNAPSHOT, data / "snapshot")
    settings = Settings(data_dir=data)
    record = run_pipeline("snapshot", settings)
    assert record.status == "success", record.error_message
    assert record.checks_failed == 0
    raw = pq.read_table(data / "snapshot" / "raw_population.parquet").to_pandas()
    return settings, raw


def raw_total(raw: pd.DataFrame, area: str, period: str, sex: str = "TOT") -> int:
    rows = raw[
        (raw["OMRÅDE"] == area)
        & (raw["KØN"] == sex)
        & (raw["ALDER"] == "IALT")
        & (raw["CIVILSTAND"] == "TOT")
        & (raw["TID"] == period)
    ]
    assert rows["INDHOLD"].nunique() == 1
    return int(rows["INDHOLD"].iloc[0])


def test_latest_copenhagen_population_equals_source_record(built):
    settings, raw = built
    db: Path = settings.warehouse_path
    latest = queries.periods(db).query("is_latest").iloc[0]
    metrics = queries.latest_metrics(db, "101")
    assert metrics["area_name"] == "Copenhagen"
    assert metrics["population"] == raw_total(raw, "101", latest.period_code)


def test_yoy_and_share_match_independent_pandas(built):
    settings, raw = built
    db = settings.warehouse_path
    latest = queries.periods(db).query("is_latest").iloc[0]
    prior = parse_period(latest.period_code).shift(-4).code
    m = queries.latest_metrics(db, "101")
    cur, prev = raw_total(raw, "101", latest.period_code), raw_total(raw, "101", prior)
    assert m["yoy_comparison_period_code"] == prior
    assert m["yoy_change"] == cur - prev
    assert m["yoy_growth_pct"] == pytest.approx((cur / prev - 1) * 100, abs=1e-12)
    dk = raw_total(raw, "000", latest.period_code)
    assert m["share_of_denmark_pct"] == pytest.approx(100 * cur / dk, abs=1e-12)


def test_copenhagen_is_the_municipality_not_the_region(built):
    settings, _ = built
    areas = queries.areas(settings.warehouse_path).set_index("area_name")
    assert areas.loc["Copenhagen", "area_code"] == "101"
    assert areas.loc["Copenhagen", "area_level"] == "municipality"
    assert areas.loc["Region Hovedstaden", "area_level"] == "region"


def test_dashboard_queries_return_data(built):
    settings, _ = built
    db = settings.warehouse_path
    periods = queries.periods(db)
    latest, first = periods.iloc[-1], periods.iloc[0]
    focus = ["101", "751", "461", "851"]
    assert len(queries.trends(db, focus)) == 4 * len(periods)
    indexed = queries.indexed_trends(db, focus, first.period_code)
    assert indexed.query("period_code == @first.period_code")["index_value"].eq(100).all()
    shares = queries.age_group_shares(db, ["101", "000"], [latest.period_code], "TOT")
    assert shares.groupby("area_code")["share_pct"].sum().round(9).eq(100).all()
    pyramid = queries.single_year_ages(db, "101", latest.period_code)
    assert set(pyramid["sex_label"]) == {"Men", "Women"}
    assert pyramid["population"].sum() == queries.latest_metrics(db, "101")["population"]
    comp = queries.comparison(db, focus, latest.period_code)
    assert comp["rank_population"].tolist() == sorted(comp["rank_population"].tolist())
    assert queries.cleaned_count(db, ["101"], ["TOT"], "total", 0, 10**9) == len(periods)
    page = queries.cleaned_page(db, None, None, "all", 0, 10**9, limit=50, offset=10)
    assert len(page) == 50
    assert queries.analytics_count(db, "mart_population_trends", None, 0, 10**9) > 0
    assert not queries.quality_results(db).query("status == 'fail'").shape[0]
    assert queries.warehouse_info(db)["table_id"] == "FOLK1A"


def test_explorer_rejects_unknown_tables_and_injection(built):
    settings, _ = built
    db = settings.warehouse_path
    with pytest.raises(ValueError):
        queries.analytics_page(db, "raw_population; DROP TABLE x", None, 0, 1, 10)
    # Filter values are bound parameters: a hostile string simply matches nothing.
    assert queries.trends(db, ["101' OR '1'='1"]).empty
