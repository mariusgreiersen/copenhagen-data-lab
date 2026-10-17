"""Structured logging.

Log calls pass context through ``extra={"ctx": {...}}``; the formatter renders it either as
``key=value`` pairs (human-readable, default) or as one JSON object per line
(``CDL_LOG_JSON=1``, convenient in CI log search).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

_CONFIGURED = False


class _StructuredFormatter(logging.Formatter):
    def __init__(self, as_json: bool) -> None:
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        ctx: dict[str, object] = getattr(record, "ctx", {}) or {}
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="seconds")
        if self.as_json:
            payload = {
                "ts": timestamp,
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                **ctx,
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str, ensure_ascii=False)
        pairs = " ".join(f"{k}={v}" for k, v in ctx.items())
        line = f"{timestamp} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if pairs:
            line = f"{line} | {pairs}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str | None = None, as_json: bool | None = None) -> None:
    """Configure the package logger once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = level or os.environ.get("CDL_LOG_LEVEL", "INFO")
    if as_json is None:
        as_json = os.environ.get("CDL_LOG_JSON", "0") == "1"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_StructuredFormatter(as_json=as_json))
    logger = logging.getLogger("copenhagen_data_lab")
    logger.setLevel(level.upper())
    logger.addHandler(handler)
    logger.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(
        name if name.startswith("copenhagen_data_lab") else f"copenhagen_data_lab.{name}"
    )
