"""Summaries and tabular forms of quality results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import pandas as pd

from copenhagen_data_lab.quality.checks import CheckResult


class QualityGateError(RuntimeError):
    """One or more critical checks failed; the dataset must not be published."""

    def __init__(self, stage: str, failures: list[CheckResult]) -> None:
        names = ", ".join(f"{f.check_id} {f.name}" for f in failures)
        super().__init__(f"{len(failures)} critical {stage} check(s) failed: {names}")
        self.stage = stage
        self.failures = failures


def summarise(results: Iterable[CheckResult]) -> dict[str, int]:
    counts = Counter(r.status for r in results)
    return {
        "passed": counts.get("pass", 0),
        "warnings": counts.get("warn", 0),
        "failed": counts.get("fail", 0),
    }


def enforce_gate(stage: str, results: list[CheckResult]) -> None:
    failures = [r for r in results if r.blocking]
    if failures:
        raise QualityGateError(stage, failures)


def to_frame(results: Iterable[CheckResult], run_id: str) -> pd.DataFrame:
    rows = [{"run_id": run_id, **r.to_json()} for r in results]
    frame = pd.DataFrame(
        rows,
        columns=[
            "run_id",
            "check_id",
            "name",
            "stage",
            "severity",
            "status",
            "records_tested",
            "invalid_records",
            "explanation",
            "executed_at_utc",
        ],
    )
    frame["executed_at_utc"] = pd.to_datetime(frame["executed_at_utc"], utc=True).dt.tz_localize(
        None
    )
    return frame
