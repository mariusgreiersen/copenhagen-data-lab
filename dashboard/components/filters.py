"""Reusable filter widgets. Filters sit in one row above the charts they scope."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import streamlit as st

from components.data import Warehouse
from components.theme import FOCUS_ORDER, MAX_SERIES


def area_table(wh: Warehouse) -> pd.DataFrame:
    return wh.load("areas")


def period_table(wh: Warehouse) -> pd.DataFrame:
    return wh.load("periods")


def area_select(
    wh: Warehouse,
    label: str,
    *,
    key: str,
    default: Sequence[str] = ("Copenhagen", "Aarhus", "Odense", "Aalborg"),
    levels: Sequence[str] = ("municipality", "country"),
    only_age_detail: bool = False,
    max_selections: int = MAX_SERIES,
    help: str | None = None,
) -> list[str]:
    """Multiselect of area *names* → returns area codes in selection order."""
    table = area_table(wh)
    table = table[table["area_level"].isin(levels)]
    if only_age_detail:
        table = table[table["has_age_detail"]]
    names = table["area_name"].tolist()
    code_of = dict(zip(table["area_name"], table["area_code"], strict=True))
    chosen = st.multiselect(
        label,
        names,
        default=[d for d in default if d in code_of],
        key=key,
        max_selections=max_selections,
        help=help,
    )
    return [code_of[n] for n in chosen]


def single_area_select(
    wh: Warehouse,
    label: str,
    *,
    key: str,
    default: str = "Copenhagen",
    only_age_detail: bool = False,
    levels: Sequence[str] = ("municipality", "country"),
) -> tuple[str, str]:
    table = area_table(wh)
    table = table[table["area_level"].isin(levels)]
    if only_age_detail:
        table = table[table["has_age_detail"]]
    names = table["area_name"].tolist()
    index = names.index(default) if default in names else 0
    name = st.selectbox(label, names, index=index, key=key)
    return table.loc[table["area_name"] == name, "area_code"].item(), name


def period_range(wh: Warehouse, *, key: str, default_start: str | None = None) -> tuple[int, int]:
    """Chronological quarter range. Returns (start_index, end_index) inclusive."""
    table = period_table(wh)
    labels = table["period_label"].tolist()
    start = default_start if default_start in labels else labels[0]
    chosen = st.select_slider(
        "Reporting period", options=labels, value=(start, labels[-1]), key=key
    )
    index_of = dict(zip(table["period_label"], table["period_index"], strict=True))
    return int(index_of[chosen[0]]), int(index_of[chosen[1]])


def period_select(
    wh: Warehouse, label: str, *, key: str, default: str | None = None, help: str | None = None
) -> tuple[str, str]:
    """Single quarter (latest by default). Returns (period_code, period_label)."""
    table = period_table(wh).iloc[::-1]
    labels = table["period_label"].tolist()
    index = labels.index(default) if default in labels else 0
    chosen = st.selectbox(label, labels, index=index, key=key, help=help)
    return table.loc[table["period_label"] == chosen, "period_code"].item(), chosen


def focus_names(wh: Warehouse) -> list[str]:
    table = area_table(wh)
    names = table.loc[table["is_focus"], "area_name"].tolist()
    return sorted(names, key=lambda n: FOCUS_ORDER.index(n) if n in FOCUS_ORDER else 99)
