"""API client tests against mocked responses (no network)."""

from __future__ import annotations

import httpx
import pytest

from copenhagen_data_lab.api.models import MetadataError
from copenhagen_data_lab.api.statbank_client import (
    StatBankClient,
    StatBankHTTPError,
    StatBankResponseError,
    StatBankUnavailableError,
)
from fixtures import synthetic


def client_for(handler, sleeps: list[float] | None = None, retries: int = 3) -> StatBankClient:
    sleeps = sleeps if sleeps is not None else []
    return StatBankClient(
        "https://api.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        max_retries=retries,
        backoff_base_s=1.0,
        backoff_max_s=5.0,
    )


def test_table_info_parses_and_keeps_verbatim_payload():
    payload = synthetic.tableinfo()
    with client_for(lambda r: httpx.Response(200, json=payload)) as client:
        info, raw = client.table_info("FOLK1A")
    assert info.id == "FOLK1A"
    assert info.variable("OMRÅDE").labels()["101"] == "Copenhagen"
    assert info.time_variable.id == "Tid"
    assert info.suppressed_data_value == "0"
    assert raw == payload


def test_request_body_is_documented_json_post():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = request.content.decode()
        return httpx.Response(200, text="A;INDHOLD\nx;1\n", headers={"content-type": "text/csv"})

    with client_for(handler) as client:
        client.data_csv("FOLK1A", {"OMRÅDE": ["101"], "Tid": ["2026K3"]})
    assert seen["method"] == "POST"
    assert '"format":"CSV"' in seen["body"].replace(" ", "")
    assert "OMRÅDE" in seen["body"]


def test_transient_failures_are_retried_with_bounded_backoff():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=synthetic.tableinfo())

    sleeps: list[float] = []
    with client_for(handler, sleeps) as client:
        info, _ = client.table_info("FOLK1A")
    assert info.id == "FOLK1A"
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]  # exponential


def test_backoff_is_capped():
    sleeps: list[float] = []
    with (
        client_for(lambda r: httpx.Response(502), sleeps, retries=5) as client,
        pytest.raises(StatBankUnavailableError),
    ):
        client.table_info("FOLK1A")
    assert sleeps == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_rate_limit_honours_retry_after():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return httpx.Response(200, json=synthetic.tableinfo())

    sleeps: list[float] = []
    with client_for(handler, sleeps) as client:
        client.table_info("FOLK1A")
    assert sleeps == [3.0]


def test_timeouts_exhaust_retries():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with client_for(handler, retries=2) as client, pytest.raises(StatBankUnavailableError) as exc:
        client.table_info("FOLK1A")
    assert "3 attempts" in str(exc.value)


def test_client_errors_are_not_retried_and_keep_api_error_code():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            400,
            json={"errorTypeCode": "EXTRACT-NOTFOUND", "message": "Kan ikke finde variablen: NOPE"},
        )

    with client_for(handler) as client, pytest.raises(StatBankHTTPError) as exc:
        client.data_csv("FOLK1A", {"NOPE": ["1"]})
    assert exc.value.error_code == "EXTRACT-NOTFOUND"
    assert calls["n"] == 1


def test_malformed_tableinfo_json():
    with (
        client_for(lambda r: httpx.Response(200, text="<html>oops</html>")) as client,
        pytest.raises(StatBankResponseError),
    ):
        client.table_info("FOLK1A")


def test_missing_mandatory_metadata_is_a_schema_error():
    broken = synthetic.tableinfo()
    del broken["unit"]
    with (
        client_for(lambda r: httpx.Response(200, json=broken)) as client,
        pytest.raises(MetadataError),
    ):
        client.table_info("FOLK1A")

    no_values = synthetic.tableinfo()
    no_values["variables"][0]["values"] = []
    with (
        client_for(lambda r: httpx.Response(200, json=no_values)) as client,
        pytest.raises(MetadataError),
    ):
        client.table_info("FOLK1A")


def test_data_must_be_csv_and_non_empty():
    with (
        client_for(lambda r: httpx.Response(200, json={"not": "csv"})) as client,
        pytest.raises(StatBankResponseError),
    ):
        client.data_csv("FOLK1A", {"Tid": ["2026K3"]})
    with (
        client_for(
            lambda r: httpx.Response(200, text="  ", headers={"content-type": "text/csv"})
        ) as client,
        pytest.raises(StatBankResponseError),
    ):
        client.data_csv("FOLK1A", {"Tid": ["2026K3"]})
