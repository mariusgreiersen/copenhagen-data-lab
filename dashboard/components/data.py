"""Warehouse bootstrap and cached query access for the dashboard.

* The dashboard never calls the StatBank API. If no published warehouse exists (e.g. a
  fresh Streamlit Cloud container) or it was built from a different snapshot, it is built
  once per process from the committed snapshot with the same offline pipeline as
  ``python -m copenhagen_data_lab.pipeline --source snapshot``.
* Query results are cached with ``st.cache_data`` keyed on the warehouse fingerprint
  (mtime + size), so publishing a new warehouse invalidates every cached result.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from copenhagen_data_lab.config.settings import get_settings
from copenhagen_data_lab.database import queries
from copenhagen_data_lab.database.connection import query_df, warehouse_version
from copenhagen_data_lab.pipeline.run import run_pipeline
from copenhagen_data_lab.pipeline.snapshot import SnapshotError, read_manifest


@dataclass(frozen=True)
class Warehouse:
    path: Path
    version: str
    snapshot_manifest: dict[str, Any] | None

    def load(self, query: str, *args: Any) -> Any:
        return _cached_query(query, str(self.path), self.version, *_hashable(args))


def _hashable(args: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(tuple(a) if isinstance(a, list) else a for a in args)


def _built_from(path: Path) -> str | None:
    try:
        return str(query_df(path, "SELECT content_sha256 FROM warehouse_info").iloc[0, 0])
    except Exception:  # noqa: BLE001 — unreadable or legacy file: rebuild
        return None


@st.cache_resource(show_spinner="Building the analytical database from the published snapshot…")
def _ensure_warehouse(snapshot_checksum: str | None) -> str:
    settings = get_settings()
    path = settings.warehouse_path
    if path.exists() and (snapshot_checksum is None or _built_from(path) == snapshot_checksum):
        return str(path)
    if snapshot_checksum is None:
        raise RuntimeError("No published warehouse and no snapshot to build one from.")
    record = run_pipeline("snapshot", settings)
    if record.status != "success":
        raise RuntimeError(
            f"Snapshot build failed at {record.failed_stage}: {record.error_message}"
        )
    return str(path)


def get_warehouse() -> Warehouse:
    settings = get_settings()
    try:
        manifest: dict[str, Any] | None = read_manifest(settings.snapshot_dir)
    except SnapshotError:
        manifest = None
    path = Path(_ensure_warehouse(manifest["content_sha256"] if manifest else None))
    return Warehouse(path=path, version=warehouse_version(path), snapshot_manifest=manifest)


@st.cache_data(show_spinner=False, max_entries=512)
def _cached_query(query: str, db_path: str, version: str, *args: Any) -> Any:
    del version  # part of the cache key only
    fn = getattr(queries, query)
    restored = tuple(list(a) if isinstance(a, tuple) else a for a in args)
    result = fn(Path(db_path), *restored)
    return result.copy() if isinstance(result, pd.DataFrame) else result


def warehouse_or_stop() -> Warehouse:
    try:
        return get_warehouse()
    except Exception as exc:  # noqa: BLE001 — surface a clear message instead of a trace
        st.error(
            "The analytical database is not available. Build it locally with "
            "`python -m copenhagen_data_lab.pipeline --source snapshot`.\n\n"
            f"Details: {exc}"
        )
        st.stop()
        raise  # unreachable; keeps type checkers happy
