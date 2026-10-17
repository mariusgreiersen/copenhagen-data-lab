"""Pipeline orchestration: Extract → Validate → Transform → Load → Verify → Publish.

Every run — successful or not — is appended to ``data/runs/pipeline_runs.jsonl``. The
published warehouse's ``pipeline_runs`` table is rebuilt from that log, so the Pipeline
Health page only ever shows runs that actually happened on this machine.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from copenhagen_data_lab import TRANSFORMATION_VERSION, __version__
from copenhagen_data_lab.api.statbank_client import StatBankClient
from copenhagen_data_lab.config.settings import Settings, get_settings
from copenhagen_data_lab.pipeline import snapshot as snap
from copenhagen_data_lab.pipeline.extract import RawExtract, extract_from_api, new_run_id
from copenhagen_data_lab.pipeline.load import append_quality_results, build_warehouse, runs_frame
from copenhagen_data_lab.pipeline.publish import cleanup_builds, finalise_build, publish_warehouse
from copenhagen_data_lab.pipeline.transform import transform
from copenhagen_data_lab.pipeline.verify import verify_warehouse
from copenhagen_data_lab.quality.checks import CheckResult, run_raw_checks
from copenhagen_data_lab.quality.report import enforce_gate, summarise, to_frame
from copenhagen_data_lab.utils.logging import get_logger

log = get_logger(__name__)

Source = Literal["api", "snapshot"]
STAGES = ("extract", "validate", "transform", "load", "verify", "publish")


@dataclass
class RunRecord:
    run_id: str
    source_mode: str
    started_at_utc: str
    status: str = "running"
    finished_at_utc: str | None = None
    duration_s: float | None = None
    failed_stage: str | None = None
    error_message: str | None = None
    records_extracted: int | None = None
    records_staged: int | None = None
    checks_passed: int | None = None
    checks_warned: int | None = None
    checks_failed: int | None = None
    snapshot_version: str | None = None
    latest_period: str | None = None
    published: bool = False
    snapshot_updated: bool = False
    pipeline_version: str = __version__
    transformation_version: str = TRANSFORMATION_VERSION
    stages: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_log(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stages_json"] = json.dumps(self.stages)
        return payload


def read_run_log(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("Skipping corrupt run-log line", extra={"ctx": {"path": str(path)}})
    return rows


def append_run_log(path: Path, record: RunRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_log(), ensure_ascii=False, default=str) + "\n")


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _warehouse_info(
    extract: RawExtract, settings: Settings, run_id: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    info, periods = extract.table_info, extract.selection.period_codes
    return {
        "build_id": run_id,
        "built_at_utc": _naive_utc(datetime.now(UTC)),
        "source_mode": extract.source_mode,
        "snapshot_version": manifest["snapshot_version"],
        "content_sha256": manifest["content_sha256"],
        "extraction_run_id": extract.extraction_run_id,
        "extracted_at_utc": _naive_utc(extract.extracted_at_utc),
        "provider": settings.provider,
        "table_id": info.id,
        "table_title": info.text,
        "unit": info.unit,
        "source_updated_local": info.updated.replace(tzinfo=None),
        "first_period": periods[0],
        "last_period": periods[-1],
        "pipeline_version": __version__,
        "transformation_version": TRANSFORMATION_VERSION,
        "manifest_json": manifest,
    }


def run_pipeline(
    source: Source,
    settings: Settings | None = None,
    *,
    client: StatBankClient | None = None,
    update_snapshot: bool = True,
) -> RunRecord:
    settings = settings or get_settings()
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    run_id = new_run_id(started)
    record = RunRecord(run_id=run_id, source_mode=source, started_at_utc=started.isoformat())
    build_path = settings.build_dir / f"{run_id}.duckdb"
    current: dict[str, Any] = {"stage": "setup", "started": t0}
    all_checks: list[CheckResult] = []

    @contextmanager
    def stage(name: str) -> Iterator[None]:
        current["stage"] = name
        s0 = current["started"] = time.perf_counter()
        log.info(f"Stage started: {name}", extra={"ctx": {"run_id": run_id}})
        status = "failed"
        try:
            yield
            status = "success"
        finally:
            record.stages.append(
                {"name": name, "status": status, "duration_s": round(time.perf_counter() - s0, 3)}
            )

    log.info("Pipeline run started", extra={"ctx": {"run_id": run_id, "source": source}})
    try:
        with stage("extract"):
            if source == "api":
                own_client = client is None
                client = client or StatBankClient(
                    settings.api_base_url,
                    timeout_s=settings.request_timeout_s,
                    max_retries=settings.max_retries,
                    backoff_base_s=settings.backoff_base_s,
                    backoff_max_s=settings.backoff_max_s,
                )
                try:
                    extract = extract_from_api(client, settings, run_id)
                finally:
                    if own_client:
                        client.close()
            else:
                extract = snap.read_snapshot(settings.snapshot_dir, settings.dimensions.period)
            record.records_extracted = len(extract.records)
            record.latest_period = extract.selection.period_codes[-1]

        with stage("validate"):
            raw_results = run_raw_checks(extract, settings)
            all_checks.extend(raw_results)
            enforce_gate("raw", raw_results)

        with stage("transform"):
            transformed = transform(extract, settings)
            record.records_staged = len(transformed.stg_population)

        with stage("load"):
            checksum = snap.content_sha256(extract.records.astype("string").astype(object))
            manifest = extract.manifest or snap.build_manifest(
                extract, settings, checksum, datetime.now(UTC)
            )
            record.snapshot_version = manifest["snapshot_version"]
            settings.build_dir.mkdir(parents=True, exist_ok=True)
            build_warehouse(
                build_path,
                extract,
                transformed,
                to_frame(raw_results, run_id),
                _warehouse_info(extract, settings, run_id, manifest),
            )

        with stage("verify"):
            post_results = verify_warehouse(build_path, extract, transformed)
            all_checks.extend(post_results)
            append_quality_results(build_path, to_frame(post_results, run_id))
            enforce_gate("post-load", post_results)

        with stage("publish"):
            if source == "api" and update_snapshot:
                existing = None
                if (settings.snapshot_dir / snap.MANIFEST_FILE).exists():
                    existing = snap.read_manifest(settings.snapshot_dir)
                if existing and existing.get("content_sha256") == checksum:
                    log.info(
                        "Source data unchanged; keeping committed snapshot",
                        extra={"ctx": {"snapshot_version": existing["snapshot_version"]}},
                    )
                    manifest = existing
                else:
                    manifest = snap.write_snapshot(
                        extract, [r.to_json() for r in raw_results], settings
                    )
                    record.snapshot_updated = True
                    log.info(
                        "Snapshot written",
                        extra={
                            "ctx": {
                                "dir": str(settings.snapshot_dir),
                                "snapshot_version": manifest["snapshot_version"],
                            }
                        },
                    )
            record.snapshot_version = manifest["snapshot_version"]
            _fill_summary(record, all_checks)
            record.status = "success"
            record.published = True
            record.finished_at_utc = datetime.now(UTC).isoformat()
            record.duration_s = round(time.perf_counter() - t0, 3)
            # The publish stage is still open here; record it as successful in the copy of
            # this run stored inside the warehouse (the swap below is the only step left).
            in_db = record.to_log()
            in_db["stages_json"] = json.dumps(
                [
                    *record.stages,
                    {
                        "name": "publish",
                        "status": "success",
                        "duration_s": round(time.perf_counter() - current["started"], 3),
                    },
                ]
            )
            history = [*read_run_log(settings.run_log_path), in_db]
            finalise_build(build_path, runs_frame(history), manifest)
            publish_warehouse(build_path, settings.warehouse_path)

    except Exception as exc:  # noqa: BLE001 — every failure is recorded, then re-reported
        record.status = "failed"
        record.published = False
        record.failed_stage = current["stage"]
        record.error_message = f"{type(exc).__name__}: {exc}"
        log.error(
            "Pipeline run failed",
            exc_info=log.isEnabledFor(10),
            extra={
                "ctx": {"run_id": run_id, "stage": current["stage"], "error": record.error_message}
            },
        )
    finally:
        _fill_summary(record, all_checks)
        record.finished_at_utc = datetime.now(UTC).isoformat()
        record.duration_s = round(time.perf_counter() - t0, 3)
        append_run_log(settings.run_log_path, record)
        cleanup_builds(settings.build_dir)

    log.info(
        "Pipeline run finished",
        extra={
            "ctx": {
                "run_id": run_id,
                "status": record.status,
                "duration_s": record.duration_s,
                "checks": f"{record.checks_passed} pass / {record.checks_warned} warn / "
                f"{record.checks_failed} fail",
            }
        },
    )
    return record


def _fill_summary(record: RunRecord, checks: list[CheckResult]) -> None:
    summary = summarise(checks)
    record.checks_passed = summary["passed"]
    record.checks_warned = summary["warnings"]
    record.checks_failed = summary["failed"]
    record.checks = [c.to_json() for c in checks]
