"""Number formatting and KPI cards.

Formatting conventions: integers with thousands separators, percentage *change* in ``%``
with an explicit sign, differences between two percentages in percentage points (``pp``).
Missing values render as an em dash — never as 0.
"""

from __future__ import annotations

import math
from html import escape

import pandas as pd
import streamlit as st

NA = "—"


def _missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(value))  # type: ignore[arg-type]
    except TypeError:
        return str(value) in {"<NA>", "NaT"}


def fmt_int(value: object) -> str:
    return NA if _missing(value) else f"{int(value):,}"  # type: ignore[call-overload]


def fmt_signed_int(value: object) -> str:
    return NA if _missing(value) else f"{int(value):+,}"  # type: ignore[call-overload]


def fmt_pct(value: object, decimals: int = 2, signed: bool = False) -> str:
    if _missing(value):
        return NA
    return f"{float(value):+.{decimals}f}%" if signed else f"{float(value):.{decimals}f}%"  # type: ignore[arg-type]


def fmt_pp(value: object, decimals: int = 2) -> str:
    return NA if _missing(value) else f"{float(value):+.{decimals}f} pp"  # type: ignore[arg-type]


def fmt_date(value: object) -> str:
    """``1 July 2026`` (portable — no platform-specific strftime flags)."""
    if _missing(value):
        return NA
    ts = pd.Timestamp(value)  # type: ignore[arg-type]
    return f"{ts.day} {ts:%B %Y}"


def fmt_timestamp(value: object) -> str:
    if _missing(value):
        return NA
    ts = pd.Timestamp(value)  # type: ignore[arg-type]
    return f"{ts.day} {ts:%b %Y, %H:%M}"


def direction(value: object) -> str:
    if _missing(value) or float(value) == 0:  # type: ignore[arg-type]
        return "flat"
    return "up" if float(value) > 0 else "down"  # type: ignore[arg-type]


def kpi_card(
    label: str,
    value: str,
    *,
    delta: str | None = None,
    delta_direction: str = "flat",
    footnote: str = "",
    kind: str = "official",
) -> None:
    """Render one KPI card.

    ``kind``: ``official`` (published by Statistics Denmark), ``derived`` (calculated here)
    or ``recorded`` (pipeline operations metadata).
    """
    arrow = {"up": "▲", "down": "▼", "flat": "●"}.get(delta_direction, "")
    value_class = "cdl-kpi-value na" if value == NA else "cdl-kpi-value"
    shown_value = "Not available" if value == NA else escape(value)
    delta_html = (
        f'<div class="cdl-kpi-delta {delta_direction}">{arrow} {escape(delta)}</div>'
        if delta
        else ""
    )
    tag = {"official": "Official figure", "derived": "Derived metric"}.get(kind, "Pipeline record")
    st.html(
        f"""<div class="cdl-kpi">
              <div class="cdl-kpi-label">{escape(label)}</div>
              <div class="{value_class}">{shown_value}</div>
              {delta_html}
              <div class="cdl-kpi-foot"><span class="cdl-tag {kind}">{tag}</span>
                <span>{escape(footnote)}</span></div>
            </div>"""
    )
