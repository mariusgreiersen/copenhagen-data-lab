"""Stage 6 — Publish.

Publication strategy (single writer, local file):

1. The warehouse is built in ``data/build/<run_id>.duckdb`` — a file nobody reads.
2. It is verified and every connection to it is closed.
3. ``Path.replace`` (``os.replace``) atomically swaps it over ``data/warehouse/copenhagen_data_lab.duckdb``.

Readers therefore see either the previous complete warehouse or the new complete one,
never a partially written file. If any stage fails, step 3 never happens and the previous
warehouse (and the committed snapshot) stay untouched. On Windows, the replace fails
while another process holds the target open, so the swap is retried briefly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from copenhagen_data_lab.pipeline.load import write_runs
from copenhagen_data_lab.utils.logging import get_logger

log = get_logger(__name__)


def finalise_build(db_path: Path, runs: pd.DataFrame, manifest: dict[str, Any]) -> None:
    """Write run history and the final snapshot manifest into the (unpublished) build."""
    write_runs(db_path, runs)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "UPDATE warehouse_info SET manifest_json = ?, snapshot_version = ?",
            [json.dumps(manifest, ensure_ascii=False), manifest["snapshot_version"]],
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()


def publish_warehouse(build_path: Path, target: Path, attempts: int = 10) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        try:
            build_path.replace(target)
            log.info("Published warehouse", extra={"ctx": {"target": str(target)}})
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(0.5 * attempt)


def cleanup_builds(build_dir: Path, keep: Path | None = None) -> None:
    for path in build_dir.glob("*.duckdb*"):
        if keep is None or path != keep:
            path.unlink(missing_ok=True)
