from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "dashboard"))

from copenhagen_data_lab.api.statbank_client import StatBankClient  # noqa: E402
from copenhagen_data_lab.config.settings import Settings  # noqa: E402
from copenhagen_data_lab.pipeline.extract import RawExtract, extract_from_api  # noqa: E402
from fixtures import synthetic  # noqa: E402

BUNDLED_SNAPSHOT = ROOT / "data" / "snapshot"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def make_client(**transport_kwargs: object) -> StatBankClient:
    return StatBankClient(
        "https://api.statbank.test/v1",
        transport=synthetic.make_transport(**transport_kwargs),
        sleep=lambda _s: None,
        max_retries=2,
    )


@pytest.fixture
def synthetic_extract(settings: Settings) -> RawExtract:
    """Extract from the mocked API using the real extraction code."""
    with make_client() as client:
        return extract_from_api(client, settings, run_id="test-run")


@pytest.fixture
def real_data_dir(tmp_path: Path) -> Path:
    """A data dir holding a copy of the committed real snapshot."""
    if not (BUNDLED_SNAPSHOT / "manifest.json").exists():
        pytest.skip("Bundled snapshot not present")
    data = tmp_path / "real"
    shutil.copytree(BUNDLED_SNAPSHOT, data / "snapshot")
    return data
