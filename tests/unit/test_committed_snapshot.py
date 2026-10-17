"""Guards on the committed real-data snapshot itself."""

from __future__ import annotations

import json

import pytest

from conftest import BUNDLED_SNAPSHOT
from copenhagen_data_lab.pipeline.snapshot import file_sha256

pytestmark = pytest.mark.skipif(
    not (BUNDLED_SNAPSHOT / "manifest.json").exists(), reason="Bundled snapshot not present"
)


def test_committed_snapshot_matches_its_manifest_checksums():
    manifest = json.loads((BUNDLED_SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        assert file_sha256(BUNDLED_SNAPSHOT / name) == expected, name


def test_committed_snapshot_uses_lf_line_endings():
    for path in BUNDLED_SNAPSHOT.glob("*.json"):
        assert b"\r" not in path.read_bytes(), f"{path.name} has CRLF line endings"


def test_committed_snapshot_has_no_personal_contact_details():
    tableinfo = json.loads((BUNDLED_SNAPSHOT / "tableinfo.json").read_text(encoding="utf-8"))
    assert "contacts" not in tableinfo
