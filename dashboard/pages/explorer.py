"""Data Explorer — inspect cleaned and analytics tables with bounded, parameterised queries."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from components.data import Warehouse, warehouse_or_stop
from components.filters import period_range
from components.layout import csv_download, facts, page_header
from components.metrics import fmt_int, fmt_timestamp
from copenhagen_data_lab.database.catalog import TABLES, definition
from copenhagen_data_lab.database.queries import MAX_EXPORT_ROWS

wh = warehouse_or_stop()
info = wh.load("warehouse_info")
areas = wh.load("areas")

page_header(
    "Data Explorer", "Inspect the validated observations and the tables behind every chart."
)

PAGE_SIZES = [100, 500, 1000]


def area_filter(key: str, all_levels: bool = True) -> list[str]:
    table = areas if all_levels else areas[areas["area_level"].isin(["municipality", "country"])]
    names = table["area_name"].tolist()
    chosen = st.multiselect("Areas (empty = all)", names, default=["Copenhagen"], key=key)
    lookup = dict(zip(table["area_name"], table["area_code"], strict=True))
    return [lookup[n] for n in chosen]


def paginate(total: int, key: str) -> tuple[int, int]:
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        size = st.selectbox("Rows per page", PAGE_SIZES, key=f"{key}_size")
    pages = max(1, math.ceil(total / size))
    with c2:
        page = st.number_input(
            "Page", min_value=1, max_value=pages, value=1, step=1, key=f"{key}_page"
        )
    with c3:
        st.html(
            f'<div style="padding-top:2rem;font-size:.85rem;color:#4a5568">'
            f"<b>{total:,}</b> matching rows · page {page} of {pages:,}</div>"
        )
    return size, (int(page) - 1) * size


def export(wh: Warehouse, query: str, args: tuple, total: int, filename: str, key: str) -> None:
    if total > MAX_EXPORT_ROWS:
        st.warning(
            f"Export is limited to {MAX_EXPORT_ROWS:,} rows; narrow the filters.",
            icon=":material/warning:",
        )
        return
    if st.toggle("Prepare CSV export of all matching rows", key=f"{key}_prep"):
        frame: pd.DataFrame = wh.load(query, *args, total, 0)
        csv_download(frame, filename, label=f"Download {len(frame):,} rows (CSV)", key=f"{key}_dl")


def column_docs(table: str, frame: pd.DataFrame) -> None:
    doc = TABLES[table]
    with st.expander(f"Column definitions — {table}", icon=":material/description:"):
        st.caption(f"Layer: {doc.layer} · Grain: {doc.grain}. {doc.description}")
        rows = [{"Column": c, "Definition": definition(table, c) or "—"} for c in frame.columns]
        st.dataframe(pd.DataFrame(rows), hide_index=True)


cleaned_tab, analytics_tab, source_tab = st.tabs(
    ["Cleaned data", "Analytics data", "Source & tables"]
)

with cleaned_tab:
    st.caption(
        "`stg_population`: validated source observations with official codes and labels. "
        "Missing values stay NULL and are flagged in `value_status`."
    )
    with st.container(border=True):
        c1, c2 = st.columns([2, 2])
        with c1:
            codes = area_filter("ex_c_areas")
        with c2:
            start, end = period_range(wh, key="ex_c_range")
        c3, c4 = st.columns([2, 2])
        with c3:
            sexes = st.multiselect(
                "Sex (empty = all)",
                ["TOT", "1", "2"],
                key="ex_c_sex",
                format_func={"TOT": "Total", "1": "Men", "2": "Women"}.get,
            )
        with c4:
            age_mode = st.segmented_control(
                "Age",
                ["total", "single", "all"],
                default="total",
                required=True,
                key="ex_c_age",
                format_func={
                    "total": "Age total only",
                    "single": "Single years",
                    "all": "All age codes",
                }.get,
            )
    args = (codes, sexes, age_mode, start, end)
    total = wh.load("cleaned_count", *args)
    size, offset = paginate(total, "ex_c")
    page = wh.load("cleaned_page", *args, size, offset)
    st.dataframe(page, hide_index=True, height=420)
    column_docs("stg_population", page)
    export(wh, "cleaned_page", args, total, "stg_population_filtered.csv", "ex_c")

with analytics_tab:
    st.caption(
        "Mart tables computed in SQL from the staging layer; these feed the dashboard charts."
    )
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.4, 2, 2])
        with c1:
            table = st.selectbox(
                "Table",
                [
                    "mart_population_trends",
                    "mart_population_demographics",
                    "mart_municipality_comparison",
                ],
                key="ex_a_table",
            )
        with c2:
            codes_a = area_filter("ex_a_areas", all_levels=table == "mart_population_trends")
        with c3:
            start_a, end_a = period_range(wh, key="ex_a_range")
    args_a = (table, codes_a, start_a, end_a)
    total_a = wh.load("analytics_count", *args_a)
    size_a, offset_a = paginate(total_a, "ex_a")
    page_a = wh.load("analytics_page", *args_a, size_a, offset_a)
    st.dataframe(page_a, hide_index=True, height=420)
    column_docs(table, page_a)
    export(wh, "analytics_page", args_a, total_a, f"{table}_filtered.csv", "ex_a")

with source_tab:
    manifest = info["manifest"]
    facts(
        [
            ("Provider", info["provider"]),
            ("Table", f"{info['table_id']} — {info['table_title']}"),
            ("Unit", f"{info['unit']} (persons)"),
            (
                "Reporting periods",
                f"{info['first_period']} – {info['last_period']} "
                f"({manifest['coverage']['period_count']} quarters)",
            ),
            ("Areas in metadata", str(manifest["coverage"]["area_count"])),
            ("Extracted", f"{fmt_timestamp(info['extracted_at_utc'])} UTC"),
            ("Content checksum (SHA-256)", info["content_sha256"][:16] + "…"),
            ("Snapshot version", info["snapshot_version"]),
        ]
    )
    st.markdown(
        f"Official table: [{info['table_id']} in StatBank](https://www.statbank.dk/{info['table_id']}) · "
        f"API: [api.statbank.dk](https://api.statbank.dk) · "
        f"Licence: [{manifest['licence']['name']}]({manifest['licence']['url']})"
    )
    st.subheader("Extraction requests", divider="gray")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Request": r["name"],
                    "Chunk": r["chunk"],
                    "Cells": fmt_int(r["cells"]),
                    "Variables": "; ".join(
                        f"{k}: {len(v)} values" for k, v in r["variables"].items()
                    ),
                    "Description": r["description"],
                }
                for r in manifest["extraction"]["requests"]
            ]
        ),
        hide_index=True,
    )
    st.subheader("Warehouse tables", divider="gray")
    counts = wh.load("table_counts")
    counts["Layer"] = counts["table_name"].map(lambda t: TABLES[t].layer if t in TABLES else "ops")
    counts["Grain"] = counts["table_name"].map(lambda t: TABLES[t].grain if t in TABLES else "—")
    st.dataframe(
        counts.rename(
            columns={"table_name": "Table", "row_count": "Rows", "column_count": "Columns"}
        ),
        hide_index=True,
    )
