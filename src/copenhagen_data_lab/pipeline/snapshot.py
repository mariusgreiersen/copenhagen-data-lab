"""Reproducible raw snapshots.

A snapshot is a directory containing:

* ``raw_population.parquet`` — every API record, all columns as the original strings
* ``tableinfo.json`` — the ``/v1/tableinfo`` response used for the extraction, minus the
  personal contact details of Statistics Denmark staff (``contacts``). The verbatim
  response stays in the local, git-ignored raw archive (``data/raw/<run_id>/``).
* ``quality_report.json`` — raw-stage quality results at extraction time
* ``manifest.json`` — provenance: source, query parameters, coverage, checksums

``content_sha256`` hashes a canonical, sorted CSV rendering of the records, so it is
independent of Parquet encoder versions and of row order. The refresh workflow compares it
with the committed snapshot to decide whether anything actually changed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from copenhagen_data_lab import TRANSFORMATION_VERSION, __version__
from copenhagen_data_lab.api.models import TableInfo
from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.extract import ExtractRequest, RawExtract, Selection
from copenhagen_data_lab.pipeline.periods import sort_period_codes

RECORDS_FILE = "raw_population.parquet"
TABLEINFO_FILE = "tableinfo.json"
QUALITY_FILE = "quality_report.json"
MANIFEST_FILE = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
# Metadata fields not republished in the committed snapshot (names, phone numbers, emails).
REDACTED_TABLEINFO_FIELDS = ("contacts",)


class SnapshotError(RuntimeError):
    """The snapshot is missing, unreadable or fails its integrity checks."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def content_sha256(records: pd.DataFrame) -> str:
    columns = list(records.columns)
    canonical = records.sort_values(columns, kind="mergesort").to_csv(
        index=False, sep=";", lineterminator="\n"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def public_tableinfo(payload: dict[str, Any]) -> dict[str, Any]:
    """Table metadata without personal contact details, for publication."""
    return {k: v for k, v in payload.items() if k not in REDACTED_TABLEINFO_FIELDS}


def snapshot_version(table_id: str, last_period: str, checksum: str) -> str:
    return f"{table_id}-{last_period}-{checksum[:10]}"


def _write_json(path: Path, payload: object) -> None:
    # Written as bytes so the file is identical on every OS: text mode would turn "\n" into
    # "\r\n" on Windows, and the manifest checksums must match on any checkout.
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    path.write_bytes(text.encode("utf-8"))


def build_manifest(
    extract: RawExtract, settings: Settings, checksum: str, published_at: datetime
) -> dict[str, Any]:
    info, selection = extract.table_info, extract.selection
    periods = selection.period_codes
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "snapshot_version": snapshot_version(info.id, periods[-1], checksum),
        "provider": settings.provider,
        "table_id": info.id,
        "table_title": info.text,
        "table_description": info.description,
        "unit": info.unit,
        "suppressed_data_value": info.suppressed_data_value,
        "source_updated_local": info.updated.isoformat(),
        "source_updated_note": "Timestamp as reported by StatBank tableinfo (Danish local time).",
        "source_url": settings.statbank_table_url,
        "api_base_url": settings.api_base_url,
        "documentation_url": info.documentation.url if info.documentation else None,
        "redacted_tableinfo_fields": list(REDACTED_TABLEINFO_FIELDS),
        "licence": {
            "name": settings.licence_name,
            "url": settings.licence_url,
            "attribution": "Source: Statistics Denmark",
        },
        "extraction": {
            "run_id": extract.extraction_run_id,
            "extracted_at_utc": extract.extracted_at_utc.isoformat(),
            "format": "CSV",
            "value_presentation": "Code",
            "language": settings.language,
            "requests": [r.to_json() for r in extract.requests],
        },
        "selection": {
            "country_code": selection.country_code,
            "primary_code": selection.primary_code,
            "focus_codes": selection.focus_codes,
            "area_levels": selection.area_levels,
        },
        "coverage": {
            "first_period": periods[0],
            "last_period": periods[-1],
            "period_count": len(periods),
            "area_count": len(selection.area_levels),
        },
        "record_count": len(extract.records),
        "content_sha256": checksum,
        "pipeline_version": __version__,
        "transformation_version": TRANSFORMATION_VERSION,
        "published_at_utc": published_at.isoformat(),
        "files": {},
    }


def write_snapshot(
    extract: RawExtract,
    quality_report: list[dict[str, Any]],
    settings: Settings,
    target_dir: Path | None = None,
) -> dict[str, Any]:
    """Write a complete snapshot to a sibling temp dir, then swap it into place."""
    target = target_dir or settings.snapshot_dir
    staging = target.with_name(target.name + ".new")
    backup = target.with_name(target.name + ".previous")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    records = extract.records.astype("string").astype(object)
    checksum = content_sha256(records)
    table = pa.Table.from_pandas(
        records, preserve_index=False, schema=pa.schema([(c, pa.string()) for c in records.columns])
    )
    pq.write_table(table, staging / RECORDS_FILE, compression="zstd", compression_level=19)
    _write_json(staging / TABLEINFO_FILE, public_tableinfo(extract.table_info_raw))
    _write_json(staging / QUALITY_FILE, quality_report)

    manifest = build_manifest(extract, settings, checksum, datetime.now(UTC))
    manifest["files"] = {
        name: file_sha256(staging / name) for name in (RECORDS_FILE, TABLEINFO_FILE, QUALITY_FILE)
    }
    _write_json(staging / MANIFEST_FILE, manifest)

    # Swap: target -> backup, staging -> target. The previous snapshot survives until the
    # new one is fully in place.
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.replace(backup)
    staging.replace(target)
    shutil.rmtree(backup, ignore_errors=True)
    return manifest


def read_manifest(snapshot_dir: Path) -> dict[str, Any]:
    path = snapshot_dir / MANIFEST_FILE
    if not path.exists():
        raise SnapshotError(f"No snapshot manifest at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_snapshot(snapshot_dir: Path, period_variable: str = "Tid") -> RawExtract:
    """Load a snapshot after verifying every file against its manifest checksum."""
    manifest = read_manifest(snapshot_dir)
    for name, expected in manifest.get("files", {}).items():
        path = snapshot_dir / name
        if not path.exists():
            raise SnapshotError(f"Snapshot file missing: {name}")
        if file_sha256(path) != expected:
            raise SnapshotError(f"Checksum mismatch for {name}; snapshot is corrupt or edited")

    info_raw = json.loads((snapshot_dir / TABLEINFO_FILE).read_text(encoding="utf-8"))
    records = pq.read_table(snapshot_dir / RECORDS_FILE).to_pandas().astype(object)
    if content_sha256(records) != manifest["content_sha256"]:
        raise SnapshotError("Record content checksum does not match manifest")

    sel = manifest["selection"]
    requests = [ExtractRequest.from_json(r) for r in manifest["extraction"]["requests"]]
    periods = sort_period_codes(
        sorted({code for r in requests for code in r.variables.get(period_variable, [])})
    )
    if not periods:
        raise SnapshotError(f"No {period_variable!r} periods recorded in manifest requests")

    return RawExtract(
        source_mode="snapshot",
        table_info=TableInfo.parse(info_raw),
        table_info_raw=info_raw,
        selection=Selection(
            country_code=sel["country_code"],
            primary_code=sel["primary_code"],
            focus_codes=dict(sel["focus_codes"]),
            area_levels=dict(sel["area_levels"]),
            period_codes=periods,
        ),
        requests=requests,
        records=records,
        extraction_run_id=manifest["extraction"]["run_id"],
        extracted_at_utc=datetime.fromisoformat(manifest["extraction"]["extracted_at_utc"]),
        manifest=manifest,
    )
