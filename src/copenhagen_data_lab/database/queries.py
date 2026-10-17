"""Analytical queries used by the dashboard.

All filter values are bound as named parameters (``$name``); identifiers such as table
names come only from fixed whitelists. Result sizes are bounded by the filters or by an
explicit ``LIMIT``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from copenhagen_data_lab.database.connection import query_df

MAX_EXPORT_ROWS = 250_000

# ---------------------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------------------


def warehouse_info(db: Path) -> dict[str, Any]:
    frame = query_df(db, "SELECT * FROM warehouse_info")
    if frame.empty:
        return {}
    row = frame.iloc[0].to_dict()
    row["manifest"] = json.loads(row.pop("manifest_json"))
    row.pop("tableinfo_json", None)
    return row


def areas(db: Path) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT area_code, area_name, area_level, is_focus, is_primary, has_age_detail
        FROM dim_area
        ORDER BY CASE area_level WHEN 'country' THEN 0 WHEN 'municipality' THEN 1
                                 WHEN 'region' THEN 2 ELSE 3 END,
                 NOT is_focus, area_name""",
    )


def periods(db: Path) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT period_code, period_label, year, quarter, period_index, reference_date, is_latest
        FROM dim_period ORDER BY period_index""",
    )


def age_groups(db: Path) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT age_group, age_group_order, MIN(age_years) AS min_age, MAX(age_years) AS max_age
        FROM dim_age WHERE NOT is_total GROUP BY ALL ORDER BY age_group_order""",
    )


# ---------------------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------------------


def trends(
    db: Path, area_codes: Sequence[str], start_index: int = -1, end_index: int = 10**9
) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT area_code, area_name, area_level, period_code, period_label, period_index,
               reference_date, population, yoy_comparison_period_code, population_year_earlier,
               yoy_change, yoy_growth_pct, qoq_change, share_of_denmark_pct
        FROM mart_population_trends
        WHERE area_code IN (SELECT UNNEST($codes::VARCHAR[]))
          AND period_index BETWEEN $start AND $end
        ORDER BY area_code, period_index""",
        {"codes": list(area_codes), "start": start_index, "end": end_index},
    )


def indexed_trends(
    db: Path,
    area_codes: Sequence[str],
    base_period: str,
    start_index: int = -1,
    end_index: int = 10**9,
) -> pd.DataFrame:
    """Index = population / population in ``base_period`` × 100 (computed per area)."""
    return query_df(
        db,
        """
        WITH base AS (
            SELECT area_code, population AS base_population
            FROM mart_population_trends WHERE period_code = $base
        )
        SELECT t.area_code, t.area_name, t.period_code, t.period_label, t.period_index,
               t.reference_date, t.population, b.base_population,
               100.0 * t.population / b.base_population::DOUBLE AS index_value
        FROM mart_population_trends AS t
        JOIN base AS b USING (area_code)
        WHERE t.area_code IN (SELECT UNNEST($codes::VARCHAR[]))
          AND t.period_index BETWEEN $start AND $end
        ORDER BY t.area_code, t.period_index""",
        {"codes": list(area_codes), "base": base_period, "start": start_index, "end": end_index},
    )


def latest_metrics(db: Path, area_code: str) -> dict[str, Any] | None:
    """Metrics for ``area_code`` in the latest published quarter (None if absent)."""
    frame = query_df(
        db,
        """
        SELECT t.*, p.is_latest
        FROM mart_population_trends AS t JOIN dim_period AS p USING (period_code)
        WHERE t.area_code = $code AND p.is_latest""",
        {"code": area_code},
    )
    return None if frame.empty else frame.iloc[0].to_dict()


def comparison(db: Path, area_codes: Sequence[str], period_code: str) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT area_code, area_name, area_level, period_code, period_label, population,
               yoy_comparison_period_code, yoy_change, yoy_growth_pct, share_of_denmark_pct,
               rank_population, rank_yoy_growth, municipality_count
        FROM mart_municipality_comparison
        WHERE area_code IN (SELECT UNNEST($codes::VARCHAR[])) AND period_code = $period
        ORDER BY population DESC""",
        {"codes": list(area_codes), "period": period_code},
    )


# ---------------------------------------------------------------------------------------
# Demographics
# ---------------------------------------------------------------------------------------


def age_group_shares(
    db: Path, area_codes: Sequence[str], period_codes: Sequence[str], sex_code: str
) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT area_code, area_name, period_code, period_label, period_index, sex_code,
               sex_label, age_group, age_group_order, min_age, max_age, population,
               age_total_population, share_pct, missing_cells
        FROM mart_population_demographics
        WHERE area_code IN (SELECT UNNEST($codes::VARCHAR[]))
          AND period_code IN (SELECT UNNEST($periods::VARCHAR[]))
          AND sex_code = $sex
        ORDER BY area_code, period_index, age_group_order""",
        {"codes": list(area_codes), "periods": list(period_codes), "sex": sex_code},
    )


def age_group_share_series(
    db: Path, area_codes: Sequence[str], age_group: str, sex_code: str
) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT area_code, area_name, period_code, period_label, period_index,
               population, share_pct
        FROM mart_population_demographics
        WHERE area_code IN (SELECT UNNEST($codes::VARCHAR[]))
          AND age_group = $group AND sex_code = $sex
        ORDER BY area_code, period_index""",
        {"codes": list(area_codes), "group": age_group, "sex": sex_code},
    )


def single_year_ages(db: Path, area_code: str, period_code: str) -> pd.DataFrame:
    """Population by single year of age and sex component (excludes total categories)."""
    return query_df(
        db,
        """
        SELECT s.sex_code, x.sex_label, a.age_years, s.population, s.value_status
        FROM stg_population AS s
        JOIN dim_age AS a USING (age_code)
        JOIN dim_sex AS x USING (sex_code)
        JOIN dim_marital_status AS m USING (marital_status_code)
        WHERE s.area_code = $area AND s.period_code = $period
          AND NOT a.is_total AND NOT x.is_total AND m.is_total
        ORDER BY x.sort_order, a.age_years""",
        {"area": area_code, "period": period_code},
    )


def sex_split(db: Path, area_code: str, period_code: str) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT x.sex_code, x.sex_label, x.is_total, s.population
        FROM stg_population AS s
        JOIN dim_sex AS x USING (sex_code)
        JOIN dim_age AS a USING (age_code)
        JOIN dim_marital_status AS m USING (marital_status_code)
        WHERE s.area_code = $area AND s.period_code = $period AND a.is_total AND m.is_total
        ORDER BY x.sort_order""",
        {"area": area_code, "period": period_code},
    )


# ---------------------------------------------------------------------------------------
# Data explorer
# ---------------------------------------------------------------------------------------

_CLEANED_SELECT = """
    SELECT p.period_code, p.period_label, s.area_code, a.area_name, a.area_level,
           s.sex_code, x.sex_label, s.age_code, g.age_label, s.marital_status_code,
           s.population, s.value_status, s.raw_value
    FROM stg_population AS s
    JOIN dim_area AS a USING (area_code)
    JOIN dim_period AS p USING (period_code)
    JOIN dim_sex AS x USING (sex_code)
    JOIN dim_age AS g USING (age_code)
"""
_CLEANED_ORDER = " ORDER BY p.period_index, a.metadata_order, x.sort_order, g.sort_order"

_AGE_FILTERS = {
    "total": " AND g.is_total",
    "single": " AND NOT g.is_total",
    "all": "",
}

ANALYTICS_TABLES = {
    "mart_population_trends": "ORDER BY period_index, area_code",
    "mart_population_demographics": "ORDER BY period_index, area_code, sex_code, age_group_order",
    "mart_municipality_comparison": "ORDER BY period_index, area_code",
}


def _cleaned_where(
    area_codes: Sequence[str] | None, sex_codes: Sequence[str] | None, age_mode: str
) -> str:
    if age_mode not in _AGE_FILTERS:
        raise ValueError(f"Unknown age mode {age_mode!r}")
    where = " WHERE p.period_index BETWEEN $start AND $end"
    if area_codes:
        where += " AND s.area_code IN (SELECT UNNEST($codes::VARCHAR[]))"
    if sex_codes:
        where += " AND s.sex_code IN (SELECT UNNEST($sexes::VARCHAR[]))"
    return where + _AGE_FILTERS[age_mode]


def _cleaned_params(
    area_codes: Sequence[str] | None,
    sex_codes: Sequence[str] | None,
    start_index: int,
    end_index: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {"start": start_index, "end": end_index}
    if area_codes:
        params["codes"] = list(area_codes)
    if sex_codes:
        params["sexes"] = list(sex_codes)
    return params


def cleaned_count(
    db: Path,
    area_codes: Sequence[str] | None,
    sex_codes: Sequence[str] | None,
    age_mode: str,
    start_index: int,
    end_index: int,
) -> int:
    sql = (
        "SELECT COUNT(*) AS n FROM ("
        + _CLEANED_SELECT
        + _cleaned_where(area_codes, sex_codes, age_mode)
        + ")"
    )
    return int(
        query_df(db, sql, _cleaned_params(area_codes, sex_codes, start_index, end_index)).iloc[0, 0]
    )


def cleaned_page(
    db: Path,
    area_codes: Sequence[str] | None,
    sex_codes: Sequence[str] | None,
    age_mode: str,
    start_index: int,
    end_index: int,
    limit: int,
    offset: int = 0,
) -> pd.DataFrame:
    sql = (
        _CLEANED_SELECT
        + _cleaned_where(area_codes, sex_codes, age_mode)
        + _CLEANED_ORDER
        + " LIMIT $limit OFFSET $offset"
    )
    params = _cleaned_params(area_codes, sex_codes, start_index, end_index)
    params.update(limit=min(int(limit), MAX_EXPORT_ROWS), offset=max(int(offset), 0))
    return query_df(db, sql, params)


def _analytics_sql(table: str, area_codes: Sequence[str] | None) -> str:
    if table not in ANALYTICS_TABLES:
        raise ValueError(f"Table {table!r} is not exposed in the explorer")
    sql = f"SELECT * FROM {table} WHERE period_index BETWEEN $start AND $end"
    if area_codes:
        sql += " AND area_code IN (SELECT UNNEST($codes::VARCHAR[]))"
    return sql


def analytics_count(
    db: Path, table: str, area_codes: Sequence[str] | None, start_index: int, end_index: int
) -> int:
    sql = f"SELECT COUNT(*) FROM ({_analytics_sql(table, area_codes)})"
    params = _cleaned_params(area_codes, None, start_index, end_index)
    return int(query_df(db, sql, params).iloc[0, 0])


def analytics_page(
    db: Path,
    table: str,
    area_codes: Sequence[str] | None,
    start_index: int,
    end_index: int,
    limit: int,
    offset: int = 0,
) -> pd.DataFrame:
    sql = (
        _analytics_sql(table, area_codes)
        + " "
        + ANALYTICS_TABLES[table]
        + " LIMIT $limit OFFSET $offset"
    )
    params = _cleaned_params(area_codes, None, start_index, end_index)
    params.update(limit=min(int(limit), MAX_EXPORT_ROWS), offset=max(int(offset), 0))
    return query_df(db, sql, params)


# ---------------------------------------------------------------------------------------
# Pipeline health
# ---------------------------------------------------------------------------------------


def pipeline_runs(db: Path, limit: int = 50) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT * FROM pipeline_runs ORDER BY started_at_utc DESC LIMIT $limit""",
        {"limit": limit},
    )


def quality_results(db: Path) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT check_id, name, stage, severity, status, records_tested, invalid_records,
               explanation, executed_at_utc
        FROM quality_results
        ORDER BY CASE stage WHEN 'raw' THEN 0 ELSE 1 END, check_id""",
    )


def table_counts(db: Path) -> pd.DataFrame:
    return query_df(
        db,
        """
        SELECT table_name, estimated_size AS row_count, column_count
        FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name""",
    )
