"""Full pipeline runs against the mocked API: success, idempotence and failure behaviour."""

from __future__ import annotations

import json

import duckdb
import pytest

from conftest import make_client
from copenhagen_data_lab.pipeline import snapshot as snap
from copenhagen_data_lab.pipeline.run import read_run_log, run_pipeline
from copenhagen_data_lab.pipeline.snapshot import file_sha256


def run_api(settings, **transport):
    with make_client(**transport) as client:
        return run_pipeline("api", settings, client=client)


def test_api_run_publishes_snapshot_and_warehouse(settings):
    record = run_api(settings)
    assert record.status == "success", record.error_message
    assert [s["name"] for s in record.stages] == [
        "extract",
        "validate",
        "transform",
        "load",
        "verify",
        "publish",
    ]
    assert record.snapshot_updated
    assert settings.warehouse_path.exists()
    manifest = snap.read_manifest(settings.snapshot_dir)
    assert manifest["table_id"] == "FOLK1A"
    assert manifest["coverage"]["last_period"] == "2024K4"
    assert manifest["record_count"] == record.records_extracted
    assert not list(settings.build_dir.glob("*.duckdb"))  # temp build cleaned up

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        runs = con.execute("SELECT status, published, stages_json FROM pipeline_runs").fetchall()
        assert runs[-1][0] == "success" and runs[-1][1]
        stages = {s["name"]: s["status"] for s in json.loads(runs[-1][2])}
        assert stages["publish"] == "success"
        failed = con.execute(
            "SELECT COUNT(*) FROM quality_results WHERE status = 'fail'"
        ).fetchone()
        assert failed[0] == 0
    finally:
        con.close()


def test_unchanged_source_does_not_rewrite_snapshot(settings):
    assert run_api(settings).snapshot_updated
    before = file_sha256(settings.snapshot_dir / "manifest.json")
    second = run_api(settings)
    assert second.status == "success"
    assert not second.snapshot_updated
    assert file_sha256(settings.snapshot_dir / "manifest.json") == before


def test_snapshot_mode_reproduces_api_build(settings):
    run_api(settings)
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    api_rows = con.execute("SELECT * FROM mart_population_trends ORDER BY ALL").fetchall()
    con.close()
    record = run_pipeline("snapshot", settings)
    assert record.status == "success", record.error_message
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    snap_rows = con.execute("SELECT * FROM mart_population_trends ORDER BY ALL").fetchall()
    con.close()
    assert api_rows == snap_rows


def published_state(settings):
    return (
        file_sha256(settings.warehouse_path),
        file_sha256(settings.snapshot_dir / "raw_population.parquet"),
    )


def test_api_outage_keeps_previous_publication(settings):
    run_api(settings)
    before = published_state(settings)
    record = run_api(settings, fail_with=503)
    assert record.status == "failed"
    assert record.failed_stage == "extract"
    assert "StatBankUnavailableError" in record.error_message
    assert not record.published
    assert published_state(settings) == before
    log = read_run_log(settings.run_log_path)
    assert [r["status"] for r in log] == ["success", "failed"]


def test_critical_quality_failure_blocks_publication(settings):
    run_api(settings)
    before = published_state(settings)

    def corrupt(rows):
        rows[0][-1] = "-1"  # negative population count

    record = run_api(settings, mutate=corrupt)
    assert record.status == "failed"
    assert record.failed_stage == "validate"
    assert record.checks_failed >= 1
    assert any(c["check_id"] == "C" and c["status"] == "fail" for c in record.checks)
    assert published_state(settings) == before


def test_schema_change_fails_extraction(settings):
    def drop_column(rows):
        for row in rows:
            del row[1]

    record = run_api(settings, mutate=drop_column)
    assert record.status == "failed"
    assert not settings.warehouse_path.exists()


def test_tampered_snapshot_is_rejected(settings):
    run_api(settings)
    manifest_path = settings.snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["raw_population.parquet"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    record = run_pipeline("snapshot", settings)
    assert record.status == "failed" and record.failed_stage == "extract"
    assert "SnapshotError" in record.error_message


@pytest.mark.parametrize("source", ["snapshot"])
def test_missing_snapshot_fails_cleanly(settings, source):
    record = run_pipeline(source, settings)
    assert record.status == "failed"
    assert read_run_log(settings.run_log_path)[-1]["failed_stage"] == "extract"


def test_published_snapshot_omits_personal_contact_details(settings):
    assert run_api(settings).status == "success"
    published = (settings.snapshot_dir / "tableinfo.json").read_text(encoding="utf-8")
    assert "contacts" not in json.loads(published)
    assert "x@example.invalid" not in published
    archived = next(settings.raw_archive_dir.glob("*/tableinfo.json")).read_text(encoding="utf-8")
    assert "contacts" in json.loads(archived)  # verbatim copy stays local (git-ignored)


def test_snapshot_files_are_byte_identical_across_platforms(settings):
    """JSON must be written with LF endings, or checksums break on another OS's checkout."""
    assert run_api(settings).status == "success"
    for path in settings.snapshot_dir.glob("*.json"):
        assert b"\r" not in path.read_bytes(), path.name
