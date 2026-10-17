"""Read-only access to the published warehouse.

Each query opens a short-lived read-only connection and closes it again. Connections are
never shared between Streamlit sessions/threads, and the pipeline can atomically replace
the file between queries (see ``pipeline/publish.py``).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


class WarehouseUnavailableError(RuntimeError):
    pass


@contextmanager
def read_only(db_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if not db_path.exists():
        raise WarehouseUnavailableError(f"No published warehouse at {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        yield con
    finally:
        con.close()


def query_df(db_path: Path, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
    with read_only(db_path) as con:
        return con.execute(sql, dict(params or {})).df()


def warehouse_version(db_path: Path) -> str:
    """Cheap fingerprint that changes whenever a new warehouse is published (cache key)."""
    stat = db_path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"
