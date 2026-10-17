"""Population Trends — absolute and indexed population, annual growth."""

from __future__ import annotations

import streamlit as st

from components.charts import line_by_area
from components.data import warehouse_or_stop
from components.filters import area_select, period_range
from components.layout import chart_card, csv_download, page_header

wh = warehouse_or_stop()
periods = wh.load("periods")
label_of = dict(zip(periods["period_index"], periods["period_label"], strict=True))
code_of = dict(zip(periods["period_index"], periods["period_code"], strict=True))

page_header("Population Trends", "How the population has developed, quarter by quarter.")

with st.container(border=True):
    c1, c2, c3 = st.columns([2.2, 2.2, 1.3])
    with c1:
        codes = area_select(
            wh, "Areas", key="pt_areas", help="Municipalities and All Denmark. Up to 8 series."
        )
    with c2:
        start, end = period_range(wh, key="pt_range")
    with c3:
        mode = st.segmented_control(
            "View", ["Absolute", "Indexed"], default="Absolute", key="pt_mode", required=True
        )
    base_index = start
    if mode == "Indexed":
        options = [i for i in periods["period_index"] if start <= i <= end]
        base_index = st.selectbox(
            "Base period (= 100)",
            options,
            index=0,
            format_func=lambda i: label_of[i],
            key="pt_base",
        )

if not codes:
    st.info("Select at least one area to see trends.", icon=":material/info:")
    st.stop()

data = wh.load("trends", codes, start, end)
if data.empty:
    st.info("No observations for this selection.", icon=":material/info:")
    st.stop()
range_text = f"{label_of[start]}–{label_of[end]}"

# --- Chart A / C: absolute or indexed -----------------------------------------------------
if mode == "Indexed":
    base_code = code_of[base_index]
    indexed = wh.load("indexed_trends", codes, base_code, start, end)
    fig = line_by_area(
        indexed,
        y="index_value",
        y_title=f"Index ({label_of[base_index]} = 100)",
        hover_format="Index %{y:.1f}",
        reference_line=100.0,
        height=420,
        order=codes,
    )
    chart_card(
        "Indexed population growth",
        fig,
        subtitle=f"Population relative to {label_of[base_index]} (= 100), {range_text}",
        table=indexed.pivot_table(
            index="period_label", columns="area_name", values="index_value", sort=False
        )
        .round(2)
        .reset_index(),
        note=f"Derived: index = population in quarter ÷ population in {label_of[base_index]} × 100. "
        "Indexing puts areas of very different size on one comparable scale.",
        key="pt_indexed",
    )
else:
    fig = line_by_area(
        data,
        y="population",
        y_title="Persons",
        hover_format="%{y:,} persons",
        height=420,
        order=codes,
    )
    chart_card(
        "Population over time",
        fig,
        subtitle=f"Persons on the first day of each quarter, {range_text}",
        table=data.pivot_table(
            index="period_label", columns="area_name", values="population", sort=False
        ).reset_index(),
        note="Official counts. Missing quarters would appear as gaps — values are never "
        "interpolated. Use the Indexed view to compare areas of different size.",
        key="pt_absolute",
    )

# --- Chart B: annual growth ---------------------------------------------------------------
growth = data.dropna(subset=["yoy_growth_pct"])
fig = (
    line_by_area(
        growth,
        y="yoy_growth_pct",
        y_title="YoY growth (%)",
        hover_format="%{y:+.2f}%",
        reference_line=0.0,
        height=360,
        order=codes,
    )
    if not growth.empty
    else None
)
if fig is not None:
    fig.update_yaxes(ticksuffix="%")
chart_card(
    "Annual population growth",
    fig,
    subtitle="% change vs the same quarter one year earlier",
    table=growth.pivot_table(
        index="period_label", columns="area_name", values="yoy_growth_pct", sort=False
    )
    .round(3)
    .reset_index()
    if not growth.empty
    else None,
    note="Derived: growth = (population ÷ population four quarters earlier − 1) × 100, computed "
    "only when that exact same quarter of the prior year exists. The first four quarters "
    "of the series therefore have no growth value.",
    empty_message="Growth needs at least five consecutive quarters in the selected range.",
    key="pt_growth",
)

# --- Export -------------------------------------------------------------------------------
export = data[
    [
        "area_code",
        "area_name",
        "period_code",
        "period_label",
        "reference_date",
        "population",
        "yoy_comparison_period_code",
        "population_year_earlier",
        "yoy_change",
        "yoy_growth_pct",
    ]
]
if mode == "Indexed":
    export = export.merge(
        indexed[["area_code", "period_code", "base_population", "index_value"]],
        on=["area_code", "period_code"],
        how="left",
    )
st.caption(f"{len(export):,} rows in the current selection.")
csv_download(
    export,
    f"copenhagen_data_lab_trends_{code_of[start]}_{code_of[end]}.csv",
    label="Download filtered data (CSV)",
    key="pt_csv",
)
