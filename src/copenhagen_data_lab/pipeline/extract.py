"""Stage 1 — Extract.

Metadata first: ``/v1/tableinfo`` is fetched and validated, area codes are resolved from
their official labels, and total codes are verified. Only then are bounded ``/v1/data``
requests built, each kept below the CSV cell limit by splitting along the time dimension.

Both source modes produce the same :class:`RawExtract` — every value is kept as the exact
string the API returned — so that validation and transformation are shared code.
"""

from __future__ import annotations

import io
import json
import math
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from copenhagen_data_lab.api.models import MetadataError, TableInfo, Variable
from copenhagen_data_lab.api.statbank_client import StatBankClient, StatBankHTTPError
from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.periods import parse_period, sort_period_codes
from copenhagen_data_lab.utils.logging import get_logger

log = get_logger(__name__)

VALUE_COLUMN = "INDHOLD"  # "content" — the observation value column in StatBank CSV
REQUEST_COLUMN = "request_name"

AREA_LEVELS = ("country", "region", "municipality", "special_area")


@dataclass(frozen=True)
class ExtractRequest:
    """One bounded ``/v1/data`` call. ``variables`` maps metadata variable ids to codes."""

    name: str
    description: str
    variables: dict[str, list[str]]
    chunk: int = 1

    @property
    def cells(self) -> int:
        return math.prod(len(v) for v in self.variables.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "chunk": self.chunk,
            "description": self.description,
            "cells": self.cells,
            "variables": self.variables,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ExtractRequest:
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            variables={k: list(v) for k, v in payload["variables"].items()},
            chunk=int(payload.get("chunk", 1)),
        )


@dataclass(frozen=True)
class Selection:
    """Codes resolved from metadata for this run."""

    country_code: str
    primary_code: str
    focus_codes: dict[str, str]  # label -> code, in configured order
    area_levels: dict[str, str]  # code -> level, every area in metadata
    period_codes: list[str]  # chronological


@dataclass
class RawExtract:
    source_mode: str  # "api" | "snapshot"
    table_info: TableInfo
    table_info_raw: dict[str, Any]
    selection: Selection
    requests: list[ExtractRequest]
    records: pd.DataFrame  # all columns are strings, exactly as received
    extraction_run_id: str
    extracted_at_utc: datetime
    manifest: dict[str, Any] | None = None
    archive_dir: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def csv_columns(self) -> list[str]:
        return expected_csv_columns(self.requests)


# --------------------------------------------------------------------------------------
# Metadata interpretation
# --------------------------------------------------------------------------------------
def expected_csv_columns(requests: list[ExtractRequest]) -> list[str]:
    """CSV headers are the upper-cased variable ids (``Tid`` -> ``TID``) plus the value."""
    ids = list(requests[0].variables) if requests else []
    return [v.upper() for v in ids] + [VALUE_COLUMN]


def classify_areas(area: Variable, settings: Settings) -> dict[str, str]:
    """Assign a geographic level to every OMRÅDE code using its official label."""
    levels: dict[str, str] = {}
    for value in area.values:
        if value.text == settings.country_label:
            levels[value.id] = "country"
        elif value.text.startswith(settings.region_label_prefix):
            levels[value.id] = "region"
        elif value.text in settings.special_area_labels:
            levels[value.id] = "special_area"
        else:
            levels[value.id] = "municipality"
    countries = [c for c, lvl in levels.items() if lvl == "country"]
    if len(countries) != 1:
        raise MetadataError(
            f"Expected one area labelled {settings.country_label!r}, found {countries}"
        )
    if not any(lvl == "region" for lvl in levels.values()):
        raise MetadataError("No regions found in area metadata; labels may have changed")
    return levels


def resolve_label(variable: Variable, label: str) -> str:
    matches = [v.id for v in variable.values if v.text == label]
    if len(matches) != 1:
        raise MetadataError(
            f"Label {label!r} matched {len(matches)} codes in {variable.id}; expected exactly one"
        )
    return matches[0]


def verify_total_code(variable: Variable, code: str) -> None:
    labels = variable.labels()
    if code not in labels:
        raise MetadataError(f"Total code {code!r} not present in {variable.id}")
    if "total" not in labels[code].lower():
        raise MetadataError(
            f"Code {code!r} in {variable.id} is labelled {labels[code]!r}, not a total category"
        )


_AGE_LABEL = re.compile(r"^(\d+) years?$")


def verify_age_codes(variable: Variable, total_code: str) -> None:
    """Every non-total age code must be a single year whose label states the same age.

    Guards against silently summing broad bands (e.g. ``"100+"``) with single years.
    """
    for value in variable.values:
        if value.id == total_code:
            continue
        match = _AGE_LABEL.match(value.text)
        if not value.id.isdigit() or match is None or int(match.group(1)) != int(value.id):
            raise MetadataError(
                f"Age code {value.id!r} ({value.text!r}) is not a single-year age category"
            )


def select_periods(time_var: Variable, settings: Settings) -> list[str]:
    codes = sort_period_codes(time_var.codes())
    first = parse_period(settings.first_period).index if settings.first_period else None
    last = parse_period(settings.last_period).index if settings.last_period else None
    for bound in (settings.first_period, settings.last_period):
        if bound and bound not in codes:
            raise MetadataError(f"Configured period {bound!r} is not published in the table")
    selected = [
        c
        for c in codes
        if (first is None or parse_period(c).index >= first)
        and (last is None or parse_period(c).index <= last)
    ]
    if not selected:
        raise MetadataError("Period selection is empty")
    return selected


def resolve_selection(info: TableInfo, settings: Settings) -> Selection:
    dims = settings.dimensions
    for variable_id in dims.all():
        info.variable(variable_id)  # raises MetadataError on schema change
    if info.time_variable.id != dims.period:
        raise MetadataError(f"Time variable is {info.time_variable.id!r}, expected {dims.period!r}")

    area = info.variable(dims.area)
    levels = classify_areas(area, settings)
    verify_total_code(info.variable(dims.sex), settings.totals.sex)
    verify_total_code(info.variable(dims.age), settings.totals.age)
    verify_total_code(info.variable(dims.marital_status), settings.totals.marital_status)
    verify_age_codes(info.variable(dims.age), settings.totals.age)

    focus = {label: resolve_label(area, label) for label in settings.focus_area_labels}
    for label, code in focus.items():
        if levels[code] != "municipality":
            raise MetadataError(
                f"Focus area {label!r} ({code}) is a {levels[code]}, not a municipality"
            )

    country = next(code for code, lvl in levels.items() if lvl == "country")
    return Selection(
        country_code=country,
        primary_code=focus[settings.primary_area_label],
        focus_codes=focus,
        area_levels=levels,
        period_codes=select_periods(info.variable(dims.period), settings),
    )


def build_requests(
    info: TableInfo, selection: Selection, settings: Settings
) -> list[ExtractRequest]:
    """Two bounded cubes from the same table (marital status fixed at its total).

    * ``area_totals`` — every area × every sex category × age total × all periods.
    * ``focus_age_detail`` — Denmark + focus municipalities × sex × every age code.
    """
    dims, totals = settings.dimensions, settings.totals
    all_areas = info.variable(dims.area).codes()
    sexes = info.variable(dims.sex).codes()
    ages = info.variable(dims.age).codes()
    detail_areas = [selection.country_code, *selection.focus_codes.values()]

    specs = [
        (
            "area_totals",
            "All areas, all sex categories, total age, total marital status",
            {
                dims.area: all_areas,
                dims.sex: sexes,
                dims.age: [totals.age],
                dims.marital_status: [totals.marital_status],
            },
        ),
        (
            "focus_age_detail",
            "Denmark and focus municipalities by sex and single year of age",
            {
                dims.area: detail_areas,
                dims.sex: sexes,
                dims.age: ages,
                dims.marital_status: [totals.marital_status],
            },
        ),
    ]
    requests: list[ExtractRequest] = []
    for name, description, fixed in specs:
        per_period = math.prod(len(v) for v in fixed.values())
        periods_per_chunk = max(1, settings.max_cells_per_request // per_period)
        periods = selection.period_codes
        for i in range(0, len(periods), periods_per_chunk):
            requests.append(
                ExtractRequest(
                    name=name,
                    description=description,
                    variables={**fixed, dims.period: periods[i : i + periods_per_chunk]},
                    chunk=i // periods_per_chunk + 1,
                )
            )
    return requests


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------
def parse_csv(text: str) -> pd.DataFrame:
    """Parse StatBank's semicolon-separated CSV keeping every value as the original string.

    ``keep_default_na=False`` matters: markers such as ``..`` or empty cells must reach
    validation untouched instead of becoming NaN (or worse, zero).
    """
    text = text.lstrip("﻿")
    frame = pd.read_csv(
        io.StringIO(text), sep=";", dtype=str, keep_default_na=False, na_filter=False
    )
    frame.columns = [c.strip() for c in frame.columns]
    return frame


# --------------------------------------------------------------------------------------
# API mode
# --------------------------------------------------------------------------------------
def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def _fetch_within_limit(
    client: StatBankClient, settings: Settings, request: ExtractRequest, depth: int = 0
) -> list[tuple[ExtractRequest, str]]:
    """Fetch a request, halving its period list whenever StatBank reports REQUEST-LIMIT.

    The server's cell estimate for the limit is larger than the product of the selected
    value counts (observed: 6x for FOLK1A), so the split is driven by the API's answer
    rather than by a guessed formula. Depth is bounded by log2(number of periods).
    """
    period_id = settings.dimensions.period
    try:
        text = client.data_csv(
            settings.table_id, request.variables, lang=settings.language, value_presentation="Code"
        )
        return [(request, text)]
    except StatBankHTTPError as exc:
        periods = request.variables[period_id]
        if exc.error_code != "REQUEST-LIMIT" or len(periods) < 2 or depth > 12:
            raise
        mid = len(periods) // 2
        log.info(
            "Request over StatBank cell limit; splitting by period",
            extra={"ctx": {"request": request.name, "periods": len(periods)}},
        )
        halves = [
            replace(request, variables={**request.variables, period_id: part})
            for part in (periods[:mid], periods[mid:])
        ]
        return [
            item
            for half in halves
            for item in _fetch_within_limit(client, settings, half, depth + 1)
        ]


def extract_from_api(client: StatBankClient, settings: Settings, run_id: str) -> RawExtract:
    extracted_at = datetime.now(UTC)
    archive = settings.raw_archive_dir / run_id
    archive.mkdir(parents=True, exist_ok=True)

    info, info_raw = client.table_info(settings.table_id, settings.language)
    (archive / "tableinfo.json").write_text(
        json.dumps(info_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not info.active:
        raise MetadataError(f"Table {info.id} is marked inactive by StatBank")
    if info.id != settings.table_id:
        raise MetadataError(f"Requested {settings.table_id}, metadata describes {info.id}")

    selection = resolve_selection(info, settings)
    requests = build_requests(info, selection, settings)
    log.info(
        "Resolved selection from metadata",
        extra={
            "ctx": {
                "table": info.id,
                "periods": len(selection.period_codes),
                "first": selection.period_codes[0],
                "last": selection.period_codes[-1],
                "focus": selection.focus_codes,
                "requests": len(requests),
                "cells": sum(r.cells for r in requests),
            }
        },
    )

    frames: list[pd.DataFrame] = []
    executed: list[ExtractRequest] = []
    for request in requests:
        for part, text in _fetch_within_limit(client, settings, request):
            part = replace(part, chunk=sum(1 for r in executed if r.name == part.name) + 1)
            executed.append(part)
            (archive / f"{part.name}_{part.chunk:02d}.csv").write_text(text, encoding="utf-8")
            frame = parse_csv(text)
            frame.insert(0, REQUEST_COLUMN, part.name)
            frames.append(frame)
            log.info(
                "Extracted cube",
                extra={
                    "ctx": {
                        "request": part.name,
                        "chunk": part.chunk,
                        "rows": len(frame),
                        "expected_cells": part.cells,
                    }
                },
            )

    records = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return RawExtract(
        source_mode="api",
        table_info=info,
        table_info_raw=info_raw,
        selection=selection,
        requests=executed,
        records=records,
        extraction_run_id=run_id,
        extracted_at_utc=extracted_at,
        archive_dir=archive,
        meta={"api_requests": client.request_count},
    )
