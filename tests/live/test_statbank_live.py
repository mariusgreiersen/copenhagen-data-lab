"""Optional smoke test against the real StatBank API.

Skipped unless CDL_LIVE_TESTS=1, so ordinary CI never depends on the live service:

    CDL_LIVE_TESTS=1 pytest tests/live -v
"""

from __future__ import annotations

import os

import pytest

from copenhagen_data_lab.api.statbank_client import StatBankClient
from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.extract import parse_csv, resolve_selection

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("CDL_LIVE_TESTS") != "1",
        reason="set CDL_LIVE_TESTS=1 to call the live StatBank API",
    ),
]


def test_live_metadata_and_tiny_extract():
    settings = Settings()
    with StatBankClient(settings.api_base_url, timeout_s=30, max_retries=2) as client:
        info, _ = client.table_info("FOLK1A", "en")
        selection = resolve_selection(info, settings)  # labels, totals and age codes verified
        assert selection.primary_code == "101"
        latest = selection.period_codes[-1]
        text = client.data_csv(
            "FOLK1A",
            {
                "OMRÅDE": [selection.country_code, selection.primary_code],
                "KØN": ["TOT"],
                "ALDER": ["IALT"],
                "CIVILSTAND": ["TOT"],
                "Tid": [latest],
            },
        )
    frame = parse_csv(text)
    assert list(frame.columns) == ["OMRÅDE", "KØN", "ALDER", "CIVILSTAND", "TID", "INDHOLD"]
    assert len(frame) == 2
    assert frame["INDHOLD"].str.fullmatch(r"\d+").all()
    values = dict(zip(frame["OMRÅDE"], frame["INDHOLD"].astype(int), strict=True))
    assert 0 < values[selection.primary_code] < values[selection.country_code]
