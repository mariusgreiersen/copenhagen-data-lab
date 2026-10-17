"""Quarter identifiers.

StatBank encodes quarters as ``YYYYKq`` (``K`` = *kvartal*), e.g. ``2026K3``. Codes must
never be ordered as plain strings in general-purpose code, so every consumer goes through
:func:`parse_period`, which yields an integer ``period_index`` that is contiguous across
year boundaries (2025K4 -> 2026K1 differ by exactly 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_QUARTER_RE = re.compile(r"^(?P<year>\d{4})K(?P<quarter>[1-4])$")


class PeriodFormatError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    quarter: int

    @property
    def code(self) -> str:
        """Original StatBank identifier, e.g. ``2026K3``."""
        return f"{self.year}K{self.quarter}"

    @property
    def label(self) -> str:
        """English display label, e.g. ``2026Q3``."""
        return f"{self.year}Q{self.quarter}"

    @property
    def index(self) -> int:
        return self.year * 4 + (self.quarter - 1)

    @property
    def reference_date(self) -> date:
        """FOLK1A counts the population on the first day of the quarter."""
        return date(self.year, 3 * (self.quarter - 1) + 1, 1)

    def shift(self, quarters: int) -> Quarter:
        return quarter_from_index(self.index + quarters)


def parse_period(code: str) -> Quarter:
    match = _QUARTER_RE.match(code.strip()) if isinstance(code, str) else None
    if match is None:
        raise PeriodFormatError(f"Not a StatBank quarter code: {code!r}")
    return Quarter(int(match["year"]), int(match["quarter"]))


def is_period_code(code: object) -> bool:
    return isinstance(code, str) and _QUARTER_RE.match(code) is not None


def quarter_from_index(index: int) -> Quarter:
    return Quarter(index // 4, index % 4 + 1)


def sort_period_codes(codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda c: parse_period(c).index)


def find_gaps(codes: list[str]) -> list[str]:
    """Quarter codes missing between the first and last of ``codes`` (chronologically)."""
    if not codes:
        return []
    indexes = {parse_period(c).index for c in codes}
    lo, hi = min(indexes), max(indexes)
    return [quarter_from_index(i).code for i in range(lo, hi + 1) if i not in indexes]
