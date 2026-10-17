from __future__ import annotations

import copy

import pandas as pd
import pytest

from copenhagen_data_lab.config.settings import DEFAULT_AGE_GROUPS, AgeGroup
from copenhagen_data_lab.pipeline.transform import (
    STAGING_KEY,
    TransformError,
    assign_age_group,
    build_dimensions,
    clean_population,
)


def with_records(extract, fn):
    clone = copy.copy(extract)
    clone.records = extract.records.copy()
    fn(clone.records)
    return clone


def test_staging_is_typed_unique_and_deduplicated(synthetic_extract, settings):
    stg = clean_population(synthetic_extract, settings)
    assert str(stg["population"].dtype) == "Int64"
    assert not stg.duplicated(STAGING_KEY).any()
    overlap = synthetic_extract.records.duplicated(
        ["OMRÅDE", "KØN", "ALDER", "CIVILSTAND", "TID"]
    ).sum()
    assert len(stg) == len(synthetic_extract.records) - overlap
    assert (stg["value_status"] == "reported").all()


def test_missing_markers_become_null_never_zero(synthetic_extract, settings):
    def mark(df):
        only_once = df.index[df["OMRÅDE"] == "706"]  # Syddjurs: returned by one request only
        df.loc[only_once[0], "INDHOLD"] = ".."
        df.loc[only_once[1], "INDHOLD"] = "0"

    stg = clean_population(with_records(synthetic_extract, mark), settings)
    missing = stg[stg["value_status"] == "missing"]
    assert len(missing) == 1
    assert missing["population"].isna().all()
    assert missing["raw_value"].iloc[0] == ".."
    zero = stg[stg["raw_value"] == "0"]
    assert zero["population"].iloc[0] == 0 and zero["value_status"].iloc[0] == "reported"


def test_conflicting_duplicates_raise(synthetic_extract, settings):
    records = synthetic_extract.records
    overlap = records[
        (records["request_name"] == "focus_age_detail") & (records["ALDER"] == "IALT")
    ].index[0]

    def conflict(df):
        df.loc[overlap, "INDHOLD"] = "1"

    with pytest.raises(TransformError):
        clean_population(with_records(synthetic_extract, conflict), settings)


def test_output_is_deterministic(synthetic_extract, settings):
    shuffled = with_records(synthetic_extract, lambda df: None)
    shuffled.records = synthetic_extract.records.sample(frac=1, random_state=7)
    pd.testing.assert_frame_equal(
        clean_population(synthetic_extract, settings), clean_population(shuffled, settings)
    )


@pytest.mark.parametrize(
    "age,group",
    [
        (0, "0–17"),
        (17, "0–17"),
        (18, "18–29"),
        (29, "18–29"),
        (30, "30–44"),
        (44, "30–44"),
        (45, "45–64"),
        (64, "45–64"),
        (65, "65+"),
        (125, "65+"),
    ],
)
def test_age_group_boundaries(age, group):
    assert assign_age_group(age, DEFAULT_AGE_GROUPS)[0] == group


def test_default_age_groups_partition_all_published_ages():
    for age in range(0, 126):
        assign_age_group(age, DEFAULT_AGE_GROUPS)  # exactly one group, else raises


def test_overlapping_or_gapped_groups_are_rejected():
    overlapping = (AgeGroup("0–20", 0, 20), AgeGroup("18+", 18, None))
    with pytest.raises(TransformError):
        assign_age_group(19, overlapping)
    gapped = (AgeGroup("0–10", 0, 10), AgeGroup("12+", 12, None))
    with pytest.raises(TransformError):
        assign_age_group(11, gapped)


def test_dimensions_from_metadata(synthetic_extract, settings):
    dims = build_dimensions(synthetic_extract, settings)
    area = dims["dim_area"].set_index("area_code")
    assert area.loc["101", "is_primary"] and area.loc["101", "has_age_detail"]
    assert area.loc["000", "area_level"] == "country"
    assert not area.loc["706", "is_focus"]
    age = dims["dim_age"].set_index("age_code")
    assert age.loc["IALT", "is_total"] and pd.isna(age.loc["IALT", "age_group"])
    assert age.loc["70", "age_group"] == "65+"
    period = dims["dim_period"]
    assert period["period_index"].is_monotonic_increasing
    assert period["is_latest"].sum() == 1
    assert period.loc[period["is_latest"], "period_code"].item() == "2024K4"
