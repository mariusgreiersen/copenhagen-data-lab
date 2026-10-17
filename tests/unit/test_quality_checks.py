"""Each check passes on consistent data and catches the defect it is designed for."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from copenhagen_data_lab.api.models import TableInfo
from copenhagen_data_lab.pipeline.extract import RawExtract
from copenhagen_data_lab.quality.checks import run_raw_checks
from copenhagen_data_lab.quality.report import QualityGateError, enforce_gate, summarise


def results_by_id(extract: RawExtract, settings) -> dict:
    return {r.check_id: r for r in run_raw_checks(extract, settings)}


def mutated(extract: RawExtract, fn) -> RawExtract:
    clone = copy.copy(extract)
    clone.records = extract.records.copy()
    fn(clone.records)
    return clone


def first_row(records, request="area_totals", area="101"):
    return records.index[(records["request_name"] == request) & (records["OMRÅDE"] == area)][0]


def test_all_checks_pass_on_consistent_data(synthetic_extract, settings):
    results = run_raw_checks(synthetic_extract, settings)
    assert {r.status for r in results} == {"pass"}, [r for r in results if r.status != "pass"]
    assert summarise(results)["failed"] == 0
    enforce_gate("raw", results)  # does not raise


def test_missing_column_fails_and_skips_content_checks(synthetic_extract, settings):
    broken = mutated(synthetic_extract, lambda df: df.drop(columns=["KØN"], inplace=True))
    results = results_by_id(broken, settings)
    assert results["A"].status == "fail"
    assert "B" not in results  # content checks need a valid structure


def test_unparseable_value_fails_type_check(synthetic_extract, settings):
    broken = mutated(
        synthetic_extract,
        lambda df: df.__setitem__("INDHOLD", df["INDHOLD"].where(df.index != 3, "12a")),
    )
    assert results_by_id(broken, settings)["B"].status == "fail"


def test_negative_count_fails(synthetic_extract, settings):
    def neg(df):
        df.loc[first_row(df), "INDHOLD"] = "-5"

    assert results_by_id(mutated(synthetic_extract, neg), settings)["C"].status == "fail"


def test_duplicate_key_fails(synthetic_extract, settings):
    broken = mutated(synthetic_extract, lambda df: None)
    broken.records = pd.concat([broken.records, broken.records.iloc[[0]]])
    results = results_by_id(broken, settings)
    assert results["D"].status == "fail"
    assert results["D"].invalid_records == 2


def test_conflicting_overlap_between_requests_fails(synthetic_extract, settings):
    records = synthetic_extract.records
    # Copenhagen's age total is returned by both requests; change only one copy.
    overlap = records[
        (records["request_name"] == "focus_age_detail")
        & (records["ALDER"] == "IALT")
        & (records["OMRÅDE"] == "101")
    ].index[0]

    def conflict(df):
        df.loc[overlap, "INDHOLD"] = "1"

    assert results_by_id(mutated(synthetic_extract, conflict), settings)["D2"].status == "fail"


def test_missing_markers_warn_then_block(synthetic_extract, settings):
    def few(df):
        df.loc[df.index[:1], "INDHOLD"] = ".."

    e = results_by_id(mutated(synthetic_extract, few), settings)["E"]
    assert e.status == "warn" and e.invalid_records == 1

    def many(df):
        df.loc[df.index[: len(df) // 10], "INDHOLD"] = ".."

    assert results_by_id(mutated(synthetic_extract, many), settings)["E"].status == "fail"


def test_zero_is_valid_not_missing(synthetic_extract, settings):
    def zero(df):
        # A zero single-age cell for an area where the totals still match is a valid count.
        df.loc[df.index[0], "INDHOLD"] = "0"

    e = results_by_id(mutated(synthetic_extract, zero), settings)["E"]
    assert e.invalid_records == 0
    assert "1 reported zeros" in e.explanation


def test_unknown_code_fails_referential_check(synthetic_extract, settings):
    def unknown(df):
        df.loc[df.index[0], "OMRÅDE"] = "999"

    assert results_by_id(mutated(synthetic_extract, unknown), settings)["G"].status == "fail"


@pytest.mark.parametrize(
    "check_id,area,sex,age",
    [
        ("H1", "101", "TOT", "IALT"),  # sex total no longer equals men + women
        ("H2", "751", "1", "IALT"),  # age total no longer equals single years
        ("H3", "000", "TOT", "IALT"),  # Denmark no longer equals municipalities
    ],
)
def test_aggregate_inconsistency_fails(synthetic_extract, settings, check_id, area, sex, age):
    def bump(df):
        mask = (
            (df["OMRÅDE"] == area)
            & (df["KØN"] == sex)
            & (df["ALDER"] == age)
            & (df["TID"] == "2024K4")
        )
        df.loc[mask, "INDHOLD"] = (df.loc[mask, "INDHOLD"].astype(int) + 1).astype(str)

    assert results_by_id(mutated(synthetic_extract, bump), settings)[check_id].status == "fail"


def test_incomplete_cube_fails(synthetic_extract, settings):
    broken = mutated(synthetic_extract, lambda df: None)
    broken.records = broken.records.iloc[1:]
    assert results_by_id(broken, settings)["R3"].status == "fail"


def test_unit_change_fails(synthetic_extract, settings):
    broken = copy.copy(synthetic_extract)
    broken.table_info = TableInfo.parse(
        {**synthetic_extract.table_info_raw, "unit": "1,000 persons"}
    )
    assert results_by_id(broken, settings)["R1"].status == "fail"


def test_time_gap_is_a_warning_not_a_failure(synthetic_extract, settings):
    gappy = copy.copy(synthetic_extract)
    gappy.selection = copy.copy(synthetic_extract.selection)
    object.__setattr__(
        gappy.selection,
        "period_codes",
        [p for p in synthetic_extract.selection.period_codes if p != "2023K2"],
    )
    f = results_by_id(gappy, settings)["F"]
    assert f.status == "warn" and "2023K2" in f.explanation


def test_gate_raises_on_critical_failure(synthetic_extract, settings):
    broken = mutated(synthetic_extract, lambda df: df.__setitem__("INDHOLD", "x"))
    with pytest.raises(QualityGateError):
        enforce_gate("raw", run_raw_checks(broken, settings))
