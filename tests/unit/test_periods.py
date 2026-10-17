from datetime import date

import pytest

from copenhagen_data_lab.pipeline.periods import (
    PeriodFormatError,
    find_gaps,
    is_period_code,
    parse_period,
    quarter_from_index,
    sort_period_codes,
)


def test_parse_period_preserves_code_and_derives_fields():
    q = parse_period("2026K3")
    assert (q.year, q.quarter) == (2026, 3)
    assert q.code == "2026K3"
    assert q.label == "2026Q3"
    assert q.reference_date == date(2026, 7, 1)


def test_period_index_is_contiguous_across_year_boundary():
    assert parse_period("2026K1").index - parse_period("2025K4").index == 1
    assert parse_period("2025K3").shift(4).code == "2026K3"
    assert quarter_from_index(parse_period("2008K1").index).code == "2008K1"


@pytest.mark.parametrize("bad", ["2026Q3", "2026K5", "2026K0", "26K1", "2026k1", "", None, 2026])
def test_invalid_codes_rejected(bad):
    assert not is_period_code(bad)
    with pytest.raises(PeriodFormatError):
        parse_period(bad)


def test_sorting_is_chronological():
    shuffled = ["2010K1", "2009K4", "2009K1", "2010K2", "2009K3"]
    assert sort_period_codes(shuffled) == ["2009K1", "2009K3", "2009K4", "2010K1", "2010K2"]


def test_find_gaps_reports_missing_quarters():
    assert find_gaps(["2020K1", "2020K2", "2020K4", "2021K2"]) == ["2020K3", "2021K1"]
    assert find_gaps(["2020K1", "2020K2"]) == []
    assert find_gaps([]) == []
