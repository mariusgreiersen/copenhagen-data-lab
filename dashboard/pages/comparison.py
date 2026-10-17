"""Municipality Comparison — same metric, same reporting period, several municipalities."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.charts import line_by_area, ranked_bars
from components.data import warehouse_or_stop
from components.filters import area_select, period_select, single_area_select
from components.layout import chart_card, csv_download, page_header
from components.metrics import NA, fmt_int, fmt_pct, fmt_pp, fmt_signed_int, kpi_card

wh = warehouse_or_stop()
periods = wh.load("periods")
areas = wh.load("areas")
country = areas[areas["area_level"] == "country"].iloc[0]
age_groups = wh.load("age_groups")["age_group"].tolist()
label_of = dict(zip(periods["period_code"], periods["period_label"], strict=True))

METRICS = {
    "Total population": ("persons", "official"),
    "Absolute population change (YoY)": ("persons", "derived"),
    "Year-over-year growth (%)": ("percent", "derived"),
    "Age-group share (%)": ("percent", "derived"),
    "Indexed growth": ("index", "derived"),
}

page_header(
    "Municipality Comparison",
    "Compare municipalities on identical metric definitions and reporting periods.",
)

with st.container(border=True):
    r1 = st.columns([1, 1, 2])
    with r1[0]:
        code_a, name_a = single_area_select(
            wh, "Municipality A", key="cmp_a", default="Copenhagen", levels=("municipality",)
        )
    with r1[1]:
        code_b, name_b = single_area_select(
            wh, "Municipality B", key="cmp_b", default="Aarhus", levels=("municipality",)
        )
    with r1[2]:
        extra = area_select(
            wh,
            "Additional municipalities",
            key="cmp_extra",
            default=("Odense", "Aalborg"),
            levels=("municipality",),
            max_selections=6,
        )
    r2 = st.columns([1.4, 1, 1, 1])
    with r2[0]:
        metric = st.selectbox("Metric", list(METRICS), key="cmp_metric")
    with r2[1]:
        period_code, period_label = period_select(wh, "Reporting period", key="cmp_period")
    age_group = base_code = None
    with r2[2]:
        if metric == "Age-group share (%)":
            age_group = st.selectbox(
                "Age group", age_groups, index=len(age_groups) - 1, key="cmp_age"
            )
        elif metric == "Indexed growth":
            base_code, _ = period_select(
                wh, "Base period (= 100)", key="cmp_base", default=periods.iloc[0]["period_label"]
            )

codes = list(dict.fromkeys([code_a, code_b, *extra]))
unit, kind = METRICS[metric]


def metric_frame(area_codes: list[str]) -> pd.DataFrame:
    """Long frame [area_code, area_name, period_code, period_label, period_index, reference_date, value]."""
    if metric == "Age-group share (%)":
        data = wh.load("age_group_share_series", area_codes, age_group, "TOT")
        data = data.merge(periods[["period_code", "reference_date"]], on="period_code")
        return data.rename(columns={"share_pct": "value"})
    if metric == "Indexed growth":
        data = wh.load("indexed_trends", area_codes, base_code)
        return data.rename(columns={"index_value": "value"})
    column = {
        "Total population": "population",
        "Absolute population change (YoY)": "yoy_change",
        "Year-over-year growth (%)": "yoy_growth_pct",
    }[metric]
    return wh.load("trends", area_codes).rename(columns={column: "value"})


series = metric_frame(codes)
at_period = series[series["period_code"] == period_code].set_index("area_code")
missing = [
    areas.set_index("area_code").loc[c, "area_name"]
    for c in codes
    if c not in at_period.index or pd.isna(at_period.loc[c, "value"])
]
reference = metric_frame([country.area_code]) if unit in ("percent", "index") else pd.DataFrame()
ref_value = (
    reference.loc[reference["period_code"] == period_code, "value"].squeeze()
    if not reference.empty
    else None
)


def fmt_value(v: object) -> str:
    if unit == "persons":
        return fmt_signed_int(v) if metric.startswith("Absolute") else fmt_int(v)
    if unit == "percent":
        return fmt_pct(v, signed=metric.startswith("Year"))
    return NA if v is None or pd.isna(v) else f"{float(v):.1f}"


def diff_text(a: object, b: object) -> str:
    if any(v is None or pd.isna(v) for v in (a, b)):
        return f"Difference: {NA}"
    d = float(a) - float(b)
    if unit == "persons":
        return f"A − B: {d:+,.0f} persons"
    if unit == "percent":
        return f"A − B: {fmt_pp(d)}"
    return f"A − B: {d:+.1f} index points"


value_a = at_period["value"].get(code_a)
value_b = at_period["value"].get(code_b)
cols = st.columns(3)
with cols[0]:
    kpi_card(f"{name_a} — A", fmt_value(value_a), footnote=f"{metric}, {period_label}", kind=kind)
with cols[1]:
    kpi_card(f"{name_b} — B", fmt_value(value_b), footnote=f"{metric}, {period_label}", kind=kind)
with cols[2]:
    kpi_card(
        "Difference",
        diff_text(value_a, value_b).split(": ", 1)[1],
        footnote="A minus B" + (" · percentage points" if unit == "percent" else ""),
        kind="derived",
    )

if missing:
    reason = (
        "single-year age detail is only extracted for the five focus municipalities"
        if metric == "Age-group share (%)"
        else "no comparable observation exists"
    )
    st.warning(
        f"Not available for {', '.join(missing)} in {period_label}: {reason}. "
        "Missing values are shown as gaps, never as zero.",
        icon=":material/info:",
    )
st.write("")

# --- Charts ---------------------------------------------------------------------------------
title_suffix = {
    "Age-group share (%)": f" — age {age_group}",
    "Indexed growth": f" — base {label_of.get(base_code, '')} = 100",
}.get(metric, "")
left, right = st.columns([1, 1.25])
with left:
    bars = at_period.reset_index().dropna(subset=["value"])
    if bars.empty:
        fig = None
    else:
        number_format = {
            "persons": "{:+,.0f}" if metric.startswith("Absolute") else "{:,.0f}",
            "percent": "{:+.2f}%" if metric.startswith("Year") else "{:.2f}%",
            "index": "{:.1f}",
        }[unit]
        fig = ranked_bars(bars, value="value", value_format=number_format, x_title=metric)
        if ref_value is not None and not pd.isna(ref_value):
            fig.add_vline(
                x=float(ref_value),
                line_width=1.5,
                line_dash="solid",
                line_color="#5b6575",
                annotation_text=f"All Denmark {number_format.format(ref_value)}",
                annotation_position="top",
                annotation_font_color="#5b6575",
                annotation_font_size=11,
            )
    chart_card(
        f"{metric}{title_suffix}",
        fig,
        subtitle=f"{period_label}",
        note="Grey line: All Denmark for the same quarter (national reference, not a municipality)."
        if ref_value is not None
        else None,
        key="cmp_bars",
    )
with right:
    hist = series.dropna(subset=["value"])
    fig = None
    if not hist.empty:
        hover = {"persons": "%{y:,} persons", "percent": "%{y:.2f}%", "index": "Index %{y:.1f}"}[
            unit
        ]
        baseline = {
            "Indexed growth": 100.0,
            "Year-over-year growth (%)": 0.0,
            "Absolute population change (YoY)": 0.0,
        }.get(metric)
        fig = line_by_area(
            hist,
            y="value",
            y_title=metric,
            hover_format=hover,
            height=380,
            reference_line=baseline,
            order=codes,
        )
        if unit == "percent":
            fig.update_yaxes(ticksuffix="%")
    chart_card(
        f"Historical comparison{title_suffix}",
        fig,
        subtitle="All published quarters",
        key="cmp_lines",
    )

# --- Table ----------------------------------------------------------------------------------
with st.container(border=True):
    st.html(
        '<div class="cdl-section">Comparison table</div>'
        f'<div class="cdl-section-sub">{period_label} · ranks are among the 98 municipalities '
        "in the same quarter</div>"
    )
    ranks = wh.load("comparison", codes, period_code).set_index("area_code")
    table = pd.DataFrame(
        {
            "Municipality": [areas.set_index("area_code").loc[c, "area_name"] for c in codes],
            **(
                {}
                if metric == "Total population"
                else {metric: [fmt_value(at_period["value"].get(c)) for c in codes]}
            ),
            "Population": [fmt_int(ranks["population"].get(c)) for c in codes],
            "Population rank": [fmt_int(ranks["rank_population"].get(c)) for c in codes],
            "YoY growth": [fmt_pct(ranks["yoy_growth_pct"].get(c), signed=True) for c in codes],
            "Growth rank": [fmt_int(ranks["rank_yoy_growth"].get(c)) for c in codes],
        }
    )
    st.dataframe(table, hide_index=True)
    csv_download(
        series,
        f"comparison_{period_code}.csv",
        label="Download metric history (CSV)",
        key="cmp_csv",
    )

with st.expander("Methodology for comparison metrics", icon=":material/functions:"):
    st.markdown(
        """
- **Same period, same definition.** Every value on this page refers to the selected quarter and
  the identical formula for each municipality; nothing is mixed across periods.
- **Total population** — official FOLK1A count on the first day of the quarter.
- **Absolute change (YoY)** — population minus population in the same quarter one year
  earlier (persons).
- **Year-over-year growth** — (population ÷ population in the same quarter a year earlier − 1)
  × 100. If that exact quarter is missing, the value is unavailable rather than substituted.
- **Age-group share** — persons in the age band ÷ the official age total for the same
  municipality and quarter × 100. Only for municipalities with single-year age detail.
- **Indexed growth** — population ÷ population in the base period × 100.
- **Differences** between two percentages are given in percentage points (pp).
- **Ranks** are among the 98 municipalities only; All Denmark and Christiansø (which is not a
  municipality) are never ranked. All Denmark appears only as a labelled reference.
"""
    )
