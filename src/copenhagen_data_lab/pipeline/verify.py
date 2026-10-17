"""Stage 5 — Verify the built warehouse before it is published.

Structural checks run in SQL against the new database; the key derived metrics are
recomputed *independently* in Pandas from the staging frame and compared with the SQL
marts, so a bug in one implementation cannot silently pass.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from copenhagen_data_lab.pipeline.extract import RawExtract
from copenhagen_data_lab.pipeline.transform import STAGING_KEY, Transformed
from copenhagen_data_lab.quality.checks import CheckResult, make_result

STAGE = "post_load"
TOLERANCE = 1e-9

MART_GRAINS = {
    "mart_population_trends": ["area_code", "period_code"],
    "mart_population_demographics": ["area_code", "period_code", "sex_code", "age_group"],
    "mart_municipality_comparison": ["area_code", "period_code"],
    "stg_population": STAGING_KEY,
}


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[object] | None = None) -> int:
    return con.execute(sql, params or []).fetchone()[0]


def _check(
    check_id: str, name: str, passed: bool, tested: int, invalid: int, text: str
) -> CheckResult:
    return make_result(
        check_id,
        name,
        stage=STAGE,
        severity="critical",
        passed=passed,
        tested=tested,
        invalid=invalid,
        explanation=text,
    )


def check_row_counts(
    con: duckdb.DuckDBPyConnection, transformed: Transformed, raw_dimension_columns: list[str]
) -> CheckResult:
    columns = ", ".join(f'"{c}"' for c in raw_dimension_columns)
    raw_cells = _scalar(
        con, f"SELECT COUNT(*) FROM (SELECT DISTINCT {columns} FROM raw_population)"
    )
    stg = _scalar(con, "SELECT COUNT(*) FROM stg_population")
    expected = len(transformed.stg_population)
    ok = stg == raw_cells == expected
    return _check(
        "V1",
        "Row counts",
        ok,
        raw_cells,
        abs(stg - raw_cells) + abs(stg - expected),
        f"Distinct raw cells {raw_cells:,}; staged {stg:,}; transformed {expected:,}.",
    )


def check_uniqueness(con: duckdb.DuckDBPyConnection) -> CheckResult:
    invalid, notes = 0, []
    for table, key in MART_GRAINS.items():
        total = _scalar(con, f"SELECT COUNT(*) FROM {table}")
        distinct = _scalar(
            con, f"SELECT COUNT(*) FROM (SELECT DISTINCT {', '.join(key)} FROM {table})"
        )
        invalid += total - distinct
        notes.append(f"{table} ({total:,})")
    return _check(
        "V2",
        "Grain uniqueness",
        invalid == 0,
        len(MART_GRAINS),
        invalid,
        "Unique at documented grain: " + "; ".join(notes) + ".",
    )


def check_required_dimensions(con: duckdb.DuckDBPyConnection) -> CheckResult:
    periods = _scalar(con, "SELECT COUNT(*) FROM dim_period")
    areas = _scalar(con, "SELECT COUNT(*) FROM dim_area")
    detail = _scalar(con, "SELECT COUNT(*) FROM dim_area WHERE has_age_detail")
    sexes = _scalar(con, "SELECT COUNT(*) FROM dim_sex")
    groups = _scalar(con, "SELECT COUNT(DISTINCT age_group) FROM dim_age WHERE NOT is_total")
    trends = _scalar(con, "SELECT COUNT(*) FROM mart_population_trends")
    demo = _scalar(con, "SELECT COUNT(*) FROM mart_population_demographics")
    primary_latest = _scalar(
        con,
        """
        SELECT COUNT(*) FROM mart_population_trends t
        JOIN dim_area a USING (area_code) JOIN dim_period p USING (period_code)
        WHERE a.is_primary AND p.is_latest AND t.population IS NOT NULL""",
    )
    expected_trends, expected_demo = areas * periods, detail * periods * sexes * groups
    invalid = abs(trends - expected_trends) + abs(demo - expected_demo) + (1 - primary_latest)
    return _check(
        "V3",
        "Expected observations",
        invalid == 0,
        expected_trends + expected_demo,
        invalid,
        f"Trends {trends:,}/{expected_trends:,} (areas × quarters); demographics "
        f"{demo:,}/{expected_demo:,} (detail areas × quarters × sex × age groups); "
        f"primary area has a latest-period value: {bool(primary_latest)}.",
    )


def check_periods(con: duckdb.DuckDBPyConnection, extract: RawExtract) -> CheckResult:
    orphan = _scalar(
        con,
        """
        SELECT COUNT(*) FROM (SELECT DISTINCT period_code FROM mart_population_trends) m
        ANTI JOIN dim_period USING (period_code)""",
    )
    future = _scalar(
        con, "SELECT COUNT(*) FROM dim_period WHERE reference_date > ?", [date.today()]
    )
    latest = con.execute("SELECT period_code FROM dim_period WHERE is_latest").fetchall()
    ok_latest = len(latest) == 1 and latest[0][0] == extract.selection.period_codes[-1]
    invalid = orphan + future + (0 if ok_latest else 1)
    return _check(
        "V4",
        "Reporting periods",
        invalid == 0,
        _scalar(con, "SELECT COUNT(*) FROM dim_period"),
        invalid,
        f"{orphan} mart periods missing from dim_period; {future} periods dated in the "
        f"future; single latest period {latest[0][0] if latest else None!r}.",
    )


def check_age_reconciliation(con: duckdb.DuckDBPyConnection) -> CheckResult:
    row = con.execute(f"""
        SELECT COUNT(*) AS groups,
               COUNT(*) FILTER (WHERE abs_diff > 0 OR share_err > {TOLERANCE}) AS bad
        FROM (
            SELECT area_code, period_code, sex_code,
                   ABS(SUM(population) - ANY_VALUE(age_total_population)) AS abs_diff,
                   ABS(SUM(share_pct) - 100.0) AS share_err
            FROM mart_population_demographics
            GROUP BY ALL
            HAVING COUNT(population) = COUNT(*)
        )""").fetchone()
    return _check(
        "V5",
        "Age groups reconcile to totals",
        row[1] == 0 and row[0] > 0,
        row[0],
        row[1],
        f"{row[0]:,} area/period/sex groups: age-group counts sum to the official total "
        "and shares sum to 100%.",
    )


def _pandas_trends(transformed: Transformed, country_code: str) -> pd.DataFrame:
    stg = transformed.stg_population
    sex_t = transformed.dim_sex.loc[transformed.dim_sex.is_total, "sex_code"].item()
    age_t = transformed.dim_age.loc[transformed.dim_age.is_total, "age_code"].item()
    mar_t = transformed.dim_marital_status.loc[
        transformed.dim_marital_status.is_total, "marital_status_code"
    ].item()
    tot = stg[
        (stg.sex_code == sex_t) & (stg.age_code == age_t) & (stg.marital_status_code == mar_t)
    ]
    tot = tot.merge(transformed.dim_period[["period_code", "year", "quarter"]], on="period_code")
    lookup = {(r.area_code, r.year, r.quarter): r.population for r in tot.itertuples()}
    denmark = {r.period_code: r.population for r in tot[tot.area_code == country_code].itertuples()}

    def growth(row: pd.Series) -> float:
        prev = lookup.get((row.area_code, row.year - 1, row.quarter), pd.NA)
        if pd.isna(prev) or pd.isna(row.population):
            return np.nan
        return 100.0 * (row.population / prev - 1)

    out = tot[["area_code", "period_code", "population"]].copy()
    out["yoy_growth_pct"] = tot.apply(growth, axis=1).astype(float)
    out["share_of_denmark_pct"] = [
        np.nan if a == country_code or pd.isna(p) else 100.0 * p / denmark[c]
        for a, c, p in zip(tot.area_code, tot.period_code, tot.population, strict=True)
    ]
    return out


def _compare(left: pd.Series, right: pd.Series) -> int:
    both_null = left.isna() & right.isna()
    close = np.isclose(left.astype(float), right.astype(float), rtol=0, atol=TOLERANCE)
    return int((~(both_null | close)).sum())


def check_independent_metrics(
    con: duckdb.DuckDBPyConnection, transformed: Transformed, extract: RawExtract
) -> list[CheckResult]:
    sql = con.execute("""
        SELECT area_code, period_code, population, yoy_growth_pct, share_of_denmark_pct
        FROM mart_population_trends""").df()
    py = _pandas_trends(transformed, extract.selection.country_code)
    merged = sql.merge(
        py, on=["area_code", "period_code"], suffixes=("_sql", "_py"), how="outer", indicator=True
    )
    unmatched = int((merged["_merge"] != "both").sum())
    yoy_bad = _compare(merged.yoy_growth_pct_sql, merged.yoy_growth_pct_py) + unmatched
    share_bad = (
        _compare(merged.share_of_denmark_pct_sql, merged.share_of_denmark_pct_py) + unmatched
    )

    lag_bad = _scalar(
        con,
        f"""
        WITH s AS (
            SELECT area_code, period_index, population, yoy_growth_pct,
                   LAG(population, 4) OVER w AS lag_pop, LAG(period_index, 4) OVER w AS lag_idx
            FROM mart_population_trends WINDOW w AS (PARTITION BY area_code ORDER BY period_index))
        SELECT COUNT(*) FROM s
        WHERE NOT (
            (yoy_growth_pct IS NULL AND (lag_idx IS DISTINCT FROM period_index - 4 OR lag_pop IS NULL))
            OR ABS(yoy_growth_pct - 100.0 * (population / lag_pop::DOUBLE - 1)) <= {TOLERANCE})""",
    )
    n = len(merged)
    return [
        _check(
            "V6",
            "Independent YoY recomputation",
            yoy_bad == 0,
            n,
            yoy_bad,
            f"Pandas same-quarter-prior-year growth matches SQL for {n - yoy_bad:,}/{n:,} rows.",
        ),
        _check(
            "V7",
            "Independent share-of-Denmark recomputation",
            share_bad == 0,
            n,
            share_bad,
            f"Pandas share of the national total matches SQL for {n - share_bad:,}/{n:,} rows.",
        ),
        _check(
            "V8",
            "Guarded LAG agrees with exact join",
            lag_bad == 0,
            n,
            lag_bad,
            "A LAG(…, 4) implementation guarded on the quarter index gives identical YoY "
            "growth to the exact same-quarter join.",
        ),
    ]


def check_no_fanout(con: duckdb.DuckDBPyConnection) -> CheckResult:
    stg_totals = _scalar(
        con,
        """
        SELECT COUNT(*) FROM stg_population s
        JOIN dim_sex x USING (sex_code) JOIN dim_age a USING (age_code)
        JOIN dim_marital_status m USING (marital_status_code)
        WHERE x.is_total AND a.is_total AND m.is_total""",
    )
    trends = _scalar(con, "SELECT COUNT(*) FROM mart_population_trends")
    comparison = _scalar(con, "SELECT COUNT(*) FROM mart_municipality_comparison")
    comp_expected = _scalar(
        con,
        """
        SELECT COUNT(*) FROM mart_population_trends WHERE area_level IN ('municipality', 'country')""",
    )
    invalid = abs(trends - stg_totals) + abs(comparison - comp_expected)
    return _check(
        "V9",
        "Joins preserve row counts",
        invalid == 0,
        stg_totals,
        invalid,
        f"Trend mart {trends:,} rows vs {stg_totals:,} staged totals; comparison mart "
        f"{comparison:,} vs {comp_expected:,} expected.",
    )


def verify_warehouse(
    db_path: Path, extract: RawExtract, transformed: Transformed
) -> list[CheckResult]:
    raw_dimension_columns = extract.csv_columns[:-1]  # every CSV column except the value
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        results = [
            check_row_counts(con, transformed, raw_dimension_columns),
            check_uniqueness(con),
            check_required_dimensions(con),
            check_periods(con, extract),
            check_age_reconciliation(con),
            *check_independent_metrics(con, transformed, extract),
            check_no_fanout(con),
        ]
    finally:
        con.close()
    return results
