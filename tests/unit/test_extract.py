from __future__ import annotations

import pytest

from conftest import make_client
from copenhagen_data_lab.api.models import MetadataError, TableInfo
from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.extract import (
    build_requests,
    extract_from_api,
    parse_csv,
    resolve_selection,
)
from fixtures import synthetic


def info(**kw) -> TableInfo:
    return TableInfo.parse(synthetic.tableinfo(**kw))


def test_parse_csv_strips_bom_and_keeps_markers_as_strings():
    frame = parse_csv("﻿OMRÅDE;TID;INDHOLD\n101;2026K3;670389\n147;2026K3;..\n411;2026K3;\n")
    assert list(frame.columns) == ["OMRÅDE", "TID", "INDHOLD"]
    assert frame["INDHOLD"].tolist() == ["670389", "..", ""]
    assert frame["OMRÅDE"].tolist() == ["101", "147", "411"]  # leading zeros survive


def test_selection_resolves_codes_from_labels(settings: Settings):
    sel = resolve_selection(info(), settings)
    assert sel.country_code == "000"
    assert sel.primary_code == "101"
    assert sel.focus_codes["Aarhus"] == "751"
    assert sel.area_levels["084"] == "region"
    assert sel.area_levels["101"] == "municipality"  # Copenhagen ≠ Region Hovedstaden
    assert sel.area_levels["411"] == "special_area"
    assert sel.period_codes[0] == "2022K1" and sel.period_codes[-1] == "2024K4"


def test_period_bounds_are_validated(settings: Settings):
    sel = resolve_selection(info(), settings.model_copy(update={"first_period": "2023K2"}))
    assert sel.period_codes[0] == "2023K2"
    with pytest.raises(MetadataError):
        resolve_selection(info(), settings.model_copy(update={"first_period": "1999K1"}))


def test_ambiguous_or_missing_labels_fail(settings: Settings):
    payload = synthetic.tableinfo()
    payload["variables"][0]["values"].append({"id": "999", "text": "Aarhus"})
    with pytest.raises(MetadataError, match="matched 2 codes"):
        resolve_selection(TableInfo.parse(payload), settings)
    with pytest.raises(MetadataError, match="matched 0 codes"):
        resolve_selection(
            info(),
            settings.model_copy(
                update={
                    "focus_area_labels": ("Copenhagen", "Atlantis"),
                    "primary_area_label": "Copenhagen",
                }
            ),
        )


def test_total_codes_are_verified_against_labels(settings: Settings):
    payload = synthetic.tableinfo()
    payload["variables"][1]["values"][0]["text"] = "Unknown"  # TOT no longer a total
    with pytest.raises(MetadataError, match="not a total"):
        resolve_selection(TableInfo.parse(payload), settings)


def test_broad_age_bands_are_rejected(settings: Settings):
    payload = synthetic.tableinfo()
    payload["variables"][2]["values"].append({"id": "100-", "text": "100 years and over"})
    with pytest.raises(MetadataError, match="single-year"):
        resolve_selection(TableInfo.parse(payload), settings)


def test_schema_change_in_variables_is_detected(settings: Settings):
    payload = synthetic.tableinfo()
    payload["variables"][1]["id"] = "SEX"
    with pytest.raises(MetadataError, match="KØN"):
        resolve_selection(TableInfo.parse(payload), settings)


def test_requests_are_bounded_and_chunked_by_period(settings: Settings):
    small = settings.model_copy(update={"max_cells_per_request": 200})
    sel = resolve_selection(info(), small)
    requests = build_requests(info(), sel, small)
    assert {r.name for r in requests} == {"area_totals", "focus_age_detail"}
    assert all(r.cells <= 200 or len(r.variables["Tid"]) == 1 for r in requests)
    periods = [p for r in requests if r.name == "area_totals" for p in r.variables["Tid"]]
    assert periods == sel.period_codes  # every period exactly once, in order
    detail = next(r for r in requests if r.name == "focus_age_detail")
    assert set(detail.variables["OMRÅDE"]) == {"000", "101", "751", "461", "851", "147"}
    assert detail.variables["CIVILSTAND"] == ["TOT"]


def test_extract_splits_requests_when_api_reports_cell_limit(settings: Settings):
    with make_client(cell_limit=400) as client:
        extract = extract_from_api(client, settings, run_id="t")
    detail = [r for r in extract.requests if r.name == "focus_age_detail"]
    assert len(detail) > 1
    assert sum(r.cells for r in extract.requests) == len(extract.records)
    assert (settings.raw_archive_dir / "t" / "tableinfo.json").exists()


def test_extract_archives_raw_responses(synthetic_extract, settings: Settings):
    files = sorted(p.name for p in (settings.raw_archive_dir / "test-run").iterdir())
    assert "tableinfo.json" in files
    assert any(f.startswith("area_totals") for f in files)
    assert synthetic_extract.records["INDHOLD"].map(type).eq(str).all()
