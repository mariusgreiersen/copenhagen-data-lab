"""Client for the Statistics Denmark StatBank API (https://api.statbank.dk/v1).

Uses documented POST requests with JSON bodies. Transient failures (timeouts, connection
errors, HTTP 429 and 5xx) are retried with bounded exponential backoff; everything else
raises immediately with the API's own error code and message.

Format note: the ``CSV`` format returns the *complete* requested cube, including explicit
zero cells, but is capped at 1,000,000 cells per request. ``BULK`` streams without a cap
but omits zero-valued cells (verified against the live API), which would make a genuine
zero indistinguishable from a missing observation. The pipeline therefore uses ``CSV`` and
splits requests to stay below the cap.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from copenhagen_data_lab.api.models import TableInfo
from copenhagen_data_lab.utils.logging import get_logger

log = get_logger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class StatBankError(RuntimeError):
    """Base class for StatBank API failures."""


class StatBankHTTPError(StatBankError):
    def __init__(self, status_code: int, error_code: str | None, message: str) -> None:
        super().__init__(f"HTTP {status_code} [{error_code or 'unknown'}]: {message}")
        self.status_code = status_code
        self.error_code = error_code


class StatBankUnavailableError(StatBankError):
    """Retries exhausted on a transient failure (timeout, connection error, 429/5xx)."""


class StatBankResponseError(StatBankError):
    """The API answered 200 but the payload is not what the documented format promises."""


class StatBankClient:
    def __init__(
        self,
        base_url: str = "https://api.statbank.dk/v1",
        *,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self._sleep = sleep
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
            headers={
                "User-Agent": "copenhagen-data-lab/1.0 (+https://github.com/mariusgreiersen/copenhagen-data-lab)"
            },
        )
        self.request_count = 0

    # -- context management --------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> StatBankClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- public API ----------------------------------------------------------------------
    def table_info(self, table_id: str, lang: str = "en") -> tuple[TableInfo, dict[str, Any]]:
        """Return validated metadata plus the verbatim JSON (kept for provenance)."""
        response = self._post("tableinfo", {"table": table_id, "format": "JSON", "lang": lang})
        try:
            payload = response.json()
        except ValueError as exc:
            raise StatBankResponseError("tableinfo did not return JSON") from exc
        return TableInfo.parse(payload), payload

    def data_csv(
        self,
        table_id: str,
        variables: Mapping[str, Sequence[str]],
        *,
        lang: str = "en",
        value_presentation: str = "Code",
    ) -> str:
        """Request a cube in the semicolon-separated ``CSV`` format and return the text."""
        body = {
            "table": table_id,
            "format": "CSV",
            "lang": lang,
            "valuePresentation": value_presentation,
            "variables": [
                {"code": code, "values": list(values)} for code, values in variables.items()
            ],
        }
        response = self._post("data", body)
        content_type = response.headers.get("content-type", "")
        if "text/csv" not in content_type:
            raise StatBankResponseError(f"Expected text/csv, got {content_type!r}")
        text = response.content.decode("utf-8-sig")
        if not text.strip():
            raise StatBankResponseError("Empty CSV response")
        return text

    # -- transport -----------------------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(float(retry_after), self.backoff_max_s)
            except ValueError:
                pass
        return min(self.backoff_base_s * (2**attempt), self.backoff_max_s)

    def _post(self, endpoint: str, body: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}/{endpoint}"
        last_error: str = ""
        for attempt in range(self.max_retries + 1):
            self.request_count += 1
            started = time.perf_counter()
            retry_after: str | None = None
            try:
                response = self._http.post(url, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                if response.status_code == 200:
                    log.info(
                        "StatBank request succeeded",
                        extra={
                            "ctx": {
                                "endpoint": endpoint,
                                "attempt": attempt + 1,
                                "bytes": len(response.content),
                                "ms": elapsed_ms,
                            }
                        },
                    )
                    return response
                if response.status_code not in _RETRYABLE_STATUS:
                    raise _http_error(response)
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after")

            if attempt == self.max_retries:
                break
            delay = self._backoff(attempt, retry_after)
            log.warning(
                "Transient StatBank failure; retrying",
                extra={
                    "ctx": {
                        "endpoint": endpoint,
                        "attempt": attempt + 1,
                        "error": last_error,
                        "retry_in_s": delay,
                    }
                },
            )
            self._sleep(delay)

        raise StatBankUnavailableError(
            f"{endpoint} failed after {self.max_retries + 1} attempts: {last_error}"
        )


def _http_error(response: httpx.Response) -> StatBankHTTPError:
    code: str | None = None
    message = response.text[:500]
    try:
        payload = response.json()
        code = payload.get("errorTypeCode")
        message = payload.get("message", message)
    except (ValueError, AttributeError):
        pass
    return StatBankHTTPError(response.status_code, code, message)
