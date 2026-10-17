"""Every dashboard page renders without exceptions against a warehouse built from the
committed real snapshot (Streamlit AppTest, no browser, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from copenhagen_data_lab.config import settings as settings_module

APP = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"
PAGES = [
    "overview",
    "population",
    "demographics",
    "comparison",
    "explorer",
    "pipeline_health",
    "methodology",
]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import shutil

    from streamlit.testing.v1 import AppTest

    from conftest import BUNDLED_SNAPSHOT

    if not (BUNDLED_SNAPSHOT / "manifest.json").exists():
        pytest.skip("Bundled snapshot not present")
    data = tmp_path_factory.mktemp("dash") / "data"
    shutil.copytree(BUNDLED_SNAPSHOT, data / "snapshot")
    previous = settings_module._cache.settings
    settings_module._cache.settings = settings_module.Settings(data_dir=data)
    try:
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.run()  # first run builds the warehouse from the snapshot (offline)
        yield at, data
    finally:
        settings_module._cache.settings = previous


def test_app_bootstraps_warehouse_from_snapshot(app):
    at, data = app
    assert not at.exception, [e.value for e in at.exception]
    assert (data / "warehouse" / "copenhagen_data_lab.duckdb").exists()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(app, page):
    at, _ = app
    at.switch_page(f"pages/{page}.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_indexed_view_and_metric_switching(app):
    at, _ = app
    at.switch_page("pages/population.py")
    at.run()
    at.segmented_control(key="pt_mode").set_value("Indexed").run()
    assert not at.exception
    at.switch_page("pages/comparison.py")
    at.run()
    for metric in ["Year-over-year growth (%)", "Age-group share (%)", "Indexed growth"]:
        at.selectbox(key="cmp_metric").set_value(metric).run()
        assert not at.exception, (metric, [e.value for e in at.exception])
