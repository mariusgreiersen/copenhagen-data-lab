"""Table and column definitions — the single source for the Data Explorer and docs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableDoc:
    name: str
    layer: str
    grain: str
    description: str
    columns: dict[str, str]


# Columns that mean the same thing in every table that has them.
COMMON_COLUMNS: dict[str, str] = {
    "area_level": "country, region, municipality or special_area (Christiansø)",
    "is_focus": "True for the five focus municipalities with single-year age detail",
    "year": "Calendar year of the quarter",
    "quarter": "Quarter number 1–4",
    "period_index": "year × 4 + quarter − 1; contiguous integer used for ordering and lags",
    "reference_date": "Date the population was counted (first day of the quarter)",
    "age_group_order": "Sort order of the age group (youngest first)",
    "source_request": "Extraction request that delivered the observation",
    "yoy_comparison_period_code": "Same quarter one year earlier, when that quarter exists",
    "population_year_earlier": "Population in the comparison quarter one year earlier",
}

TABLES: dict[str, TableDoc] = {
    "raw_population": TableDoc(
        "raw_population",
        "raw",
        "One row per requested cell per extraction request",
        "StatBank CSV records exactly as received; every column is a string.",
        {
            "extraction_run_id": "Pipeline run that downloaded the records",
            "request_name": "Bounded API request that returned the record",
            "OMRÅDE": "Area code (StatBank)",
            "KØN": "Sex code (StatBank)",
            "ALDER": "Age code (StatBank)",
            "CIVILSTAND": "Marital status code (StatBank)",
            "TID": "Quarter code, e.g. 2026K3",
            "INDHOLD": "Observation value as text (persons)",
        },
    ),
    "stg_population": TableDoc(
        "stg_population",
        "staging",
        "area × sex × age × marital status × quarter",
        "Cleaned, typed observations. Missing values are NULL with value_status='missing'.",
        {
            "period_code": "Original StatBank quarter code (e.g. 2026K3)",
            "period_label": "Display label (e.g. 2026Q3)",
            "area_code": "StatBank area code",
            "area_name": "Official English area name",
            "area_level": "country, region, municipality or special_area (Christiansø)",
            "sex_code": "TOT, 1 (men) or 2 (women)",
            "sex_label": "Official sex category label",
            "age_code": "IALT (age total) or single year 0–125",
            "age_label": "Official age label",
            "marital_status_code": "Marital status code (TOT = all)",
            "population": "Persons on the first day of the quarter (official figure)",
            "value_status": "reported or missing",
            "raw_value": "Value exactly as delivered by StatBank",
        },
    ),
    "mart_population_trends": TableDoc(
        "mart_population_trends",
        "mart",
        "area × quarter (all sexes, all ages)",
        "Population totals with derived growth metrics.",
        {
            "area_code": "StatBank area code",
            "area_name": "Official English area name",
            "area_level": "country, region, municipality or special_area",
            "period_code": "StatBank quarter code",
            "period_label": "Display label",
            "reference_date": "Date the population was counted (first day of quarter)",
            "population": "Official population count",
            "yoy_comparison_period_code": "Same quarter one year earlier, when available",
            "population_year_earlier": "Population in that comparison quarter",
            "yoy_change": "Derived: population − population one year earlier (persons)",
            "yoy_growth_pct": "Derived: (population / population one year earlier − 1) × 100",
            "population_previous_quarter": "Population in the immediately preceding quarter",
            "qoq_change": "Derived: change from the preceding quarter (persons)",
            "denmark_population": "All Denmark population in the same quarter",
            "share_of_denmark_pct": "Derived: population / All Denmark × 100 (same quarter)",
        },
    ),
    "mart_population_demographics": TableDoc(
        "mart_population_demographics",
        "mart",
        "area × quarter × sex × age group (Denmark + focus municipalities)",
        "Age groups built from single-year ages; shares of the official age total.",
        {
            "area_code": "StatBank area code",
            "area_name": "Official English area name",
            "period_code": "StatBank quarter code",
            "period_label": "Display label",
            "sex_code": "TOT, 1 (men) or 2 (women)",
            "sex_label": "Official sex category label",
            "age_group": "Derived age band (0–17, 18–29, 30–44, 45–64, 65+)",
            "min_age": "Youngest single-year age in the band",
            "max_age": "Oldest single-year age in the band",
            "population": "Derived: sum of single-year counts (NULL if any are missing)",
            "age_total_population": "Official age total for the same area/quarter/sex",
            "share_pct": "Derived: population / age_total_population × 100",
            "single_year_cells": "Number of single-year ages in the band",
            "missing_cells": "Single-year ages with a missing value",
        },
    ),
    "mart_municipality_comparison": TableDoc(
        "mart_municipality_comparison",
        "mart",
        "area × quarter (municipalities and All Denmark)",
        "Population metrics with ranks among the 98 municipalities in the same quarter.",
        {
            "area_code": "StatBank area code",
            "area_name": "Official English area name",
            "area_level": "municipality or country",
            "period_code": "StatBank quarter code",
            "period_label": "Display label",
            "population": "Official population count",
            "yoy_change": "Derived: change vs same quarter one year earlier (persons)",
            "yoy_growth_pct": "Derived: YoY growth (%)",
            "share_of_denmark_pct": "Derived: share of All Denmark (%)",
            "rank_population": "Derived: rank by population among municipalities (1 = largest)",
            "rank_yoy_growth": "Derived: rank by YoY growth among municipalities (1 = fastest)",
            "municipality_count": "Municipalities ranked in that quarter",
        },
    ),
}


def definition(table: str, column: str) -> str:
    doc = TABLES.get(table)
    if doc and column in doc.columns:
        return doc.columns[column]
    return COMMON_COLUMNS.get(column, "")
