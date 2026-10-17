"""Stage 3 — Transform (Pandas part).

Turns raw string records into a typed staging frame and builds dimension tables from the
table metadata. Analytical aggregation happens afterwards in SQL (``sql/marts``).

Rules enforced here:
* values are converted to nullable integers; missing markers become NULL, never 0
* the original string value and a ``value_status`` flag are kept alongside
* observations requested by two overlapping cubes are de-duplicated only when identical
* output order is deterministic
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from copenhagen_data_lab.config.settings import AgeGroup, Settings
from copenhagen_data_lab.pipeline.extract import REQUEST_COLUMN, VALUE_COLUMN, RawExtract
from copenhagen_data_lab.pipeline.periods import parse_period
from copenhagen_data_lab.quality.checks import INTEGER_PATTERN

STAGING_KEY = ["area_code", "sex_code", "age_code", "marital_status_code", "period_code"]


class TransformError(RuntimeError):
    pass


@dataclass
class Transformed:
    stg_population: pd.DataFrame
    dim_area: pd.DataFrame
    dim_sex: pd.DataFrame
    dim_age: pd.DataFrame
    dim_marital_status: pd.DataFrame
    dim_period: pd.DataFrame


def clean_population(extract: RawExtract, settings: Settings) -> pd.DataFrame:
    dims = settings.dimensions
    rename = {
        dims.area.upper(): "area_code",
        dims.sex.upper(): "sex_code",
        dims.age.upper(): "age_code",
        dims.marital_status.upper(): "marital_status_code",
        dims.period.upper(): "period_code",
        VALUE_COLUMN: "raw_value",
        REQUEST_COLUMN: "source_request",
    }
    frame = extract.records.rename(columns=rename)[list(rename.values())].copy()
    for column in frame.columns:
        frame[column] = frame[column].astype(str).str.strip()

    # Overlapping cubes return some cells twice. Identical copies collapse to one row;
    # conflicting copies are a data error (also caught by quality check D2).
    frame = frame.sort_values([*STAGING_KEY, "source_request"], kind="mergesort")
    frame = frame.drop_duplicates([*STAGING_KEY, "raw_value"], keep="first")
    if frame.duplicated(STAGING_KEY).any():
        raise TransformError("Conflicting values for the same observation across requests")

    reported = frame["raw_value"].str.fullmatch(INTEGER_PATTERN)
    frame["value_status"] = reported.map({True: "reported", False: "missing"})
    frame["population"] = pd.array(
        [int(v) if ok else pd.NA for v, ok in zip(frame["raw_value"], reported, strict=True)],
        dtype="Int64",
    )

    columns = [*STAGING_KEY, "population", "value_status", "raw_value", "source_request"]
    return frame[columns].sort_values(STAGING_KEY, kind="mergesort").reset_index(drop=True)


def assign_age_group(age: int, groups: tuple[AgeGroup, ...]) -> tuple[str, int]:
    hits = [(g.label, i + 1) for i, g in enumerate(groups) if g.contains(age)]
    if len(hits) != 1:
        raise TransformError(
            f"Age {age} falls in {len(hits)} age groups; groups must partition ages"
        )
    return hits[0]


def build_dimensions(extract: RawExtract, settings: Settings) -> dict[str, pd.DataFrame]:
    info, sel = extract.table_info, extract.selection
    dims, totals = settings.dimensions, settings.totals
    focus = set(sel.focus_codes.values())

    area_var = info.variable(dims.area)
    dim_area = pd.DataFrame(
        [
            {
                "area_code": v.id,
                "area_name": v.text,
                "area_level": sel.area_levels[v.id],
                "is_focus": v.id in focus,
                "is_primary": v.id == sel.primary_code,
                "has_age_detail": v.id in focus or v.id == sel.country_code,
                "metadata_order": i,
            }
            for i, v in enumerate(area_var.values)
        ]
    )

    dim_sex = pd.DataFrame(
        [
            {"sex_code": v.id, "sex_label": v.text, "is_total": v.id == totals.sex, "sort_order": i}
            for i, v in enumerate(info.variable(dims.sex).values)
        ]
    )
    dim_marital = pd.DataFrame(
        [
            {
                "marital_status_code": v.id,
                "marital_status_label": v.text,
                "is_total": v.id == totals.marital_status,
                "sort_order": i,
            }
            for i, v in enumerate(info.variable(dims.marital_status).values)
        ]
    )

    age_rows = []
    for i, v in enumerate(info.variable(dims.age).values):
        if v.id == totals.age:
            age_rows.append(
                {
                    "age_code": v.id,
                    "age_label": v.text,
                    "is_total": True,
                    "age_years": None,
                    "age_group": None,
                    "age_group_order": None,
                    "sort_order": i,
                }
            )
        else:
            years = int(v.id)
            group, order = assign_age_group(years, settings.age_groups)
            age_rows.append(
                {
                    "age_code": v.id,
                    "age_label": v.text,
                    "is_total": False,
                    "age_years": years,
                    "age_group": group,
                    "age_group_order": order,
                    "sort_order": i,
                }
            )
    dim_age = pd.DataFrame(age_rows)
    dim_age["age_years"] = dim_age["age_years"].astype("Int64")
    dim_age["age_group_order"] = dim_age["age_group_order"].astype("Int64")

    labels = info.variable(dims.period).labels()
    quarters = [parse_period(c) for c in sel.period_codes]
    latest = max(q.index for q in quarters)
    dim_period = pd.DataFrame(
        [
            {
                "period_code": q.code,
                "period_label": labels.get(q.code, q.label),
                "year": q.year,
                "quarter": q.quarter,
                "period_index": q.index,
                "reference_date": q.reference_date,
                "is_latest": q.index == latest,
            }
            for q in sorted(quarters)
        ]
    )
    dim_period["reference_date"] = pd.to_datetime(dim_period["reference_date"])

    return {
        "dim_area": dim_area,
        "dim_sex": dim_sex,
        "dim_age": dim_age,
        "dim_marital_status": dim_marital,
        "dim_period": dim_period,
    }


def transform(extract: RawExtract, settings: Settings) -> Transformed:
    stg = clean_population(extract, settings)
    dims = build_dimensions(extract, settings)
    return Transformed(stg_population=stg, **dims)
