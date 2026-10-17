"""Overview — executive summary for Copenhagen municipality."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.charts import age_share_bars, growth_bars, line_by_area, ranked_bars
from components.data import warehouse_or_stop
from components.filters import focus_names
from components.layout import chart_card, facts, page_header
from components.metrics import (
    NA,
    direction,
    fmt_date,
    fmt_int,
    fmt_pct,
    fmt_pp,
    fmt_signed_int,
    fmt_timestamp,
    kpi_card,
)
from components.theme import COUNTRY_NAME, REFERENCE, SERIES

wh = warehouse_or_stop()
info = wh.load("warehouse_info")
areas = wh.load("areas")
periods = wh.load("periods")
primary = areas[areas["is_primary"]].iloc[0]
country = areas[areas["area_level"] == "country"].iloc[0]
latest = periods[periods["is_latest"]].iloc[0]

page_header(
    "Copenhagen Data Lab",
    "Explore Copenhagen through official data.",
    eyebrow=f"{primary.area_name} municipality · {latest.period_label}",
)

# --- KPI row -------------------------------------------------------------------------------
m = wh.load("latest_metrics", primary.area_code) or {}
history = wh.load("trends", [primary.area_code])
year_earlier = history[history["period_code"] == m.get("yoy_comparison_period_code")]
share_change = m.get("share_of_denmark_pct", float("nan")) - (
    year_earlier["share_of_denmark_pct"].iloc[0] if not year_earlier.empty else float("nan")
)
comparison_label = (
    periods.loc[
        periods["period_code"] == m.get("yoy_comparison_period_code"), "period_label"
    ].squeeze()
    if m
    else None
)
vs = f"vs {comparison_label}" if isinstance(comparison_label, str) else "no comparable quarter"

cols = st.columns(5)
with cols[0]:
    kpi_card(
        f"{primary.area_name} population",
        fmt_int(m.get("population")),
        footnote=f"Counted {fmt_date(latest.reference_date)}",
        kind="official",
    )
with cols[1]:
    growth = m.get("yoy_growth_pct")
    kpi_card(
        "Year-over-year growth",
        fmt_pct(growth, signed=True),
        delta=vs,
        delta_direction=direction(growth),
        footnote="Same quarter, prior year",
        kind="derived",
    )
with cols[2]:
    change = m.get("yoy_change")
    kpi_card(
        "Population change",
        fmt_signed_int(change),
        delta=f"persons {vs}",
        delta_direction=direction(change),
        footnote="Absolute YoY difference",
        kind="derived",
    )
with cols[3]:
    kpi_card(
        "Share of Denmark",
        fmt_pct(m.get("share_of_denmark_pct")),
        delta=f"{fmt_pp(share_change)} {vs}" if fmt_pp(share_change) != NA else None,
        delta_direction=direction(share_change),
        footnote=f"Of {fmt_int(m.get('denmark_population'))} residents",
        kind="derived",
    )
with cols[4]:
    kpi_card(
        "Latest data period",
        str(latest.period_label),
        footnote=f"StatBank table updated {fmt_date(info['source_updated_local'])}",
        kind="official",
    )

st.write("")

# --- Row 1: trend + freshness --------------------------------------------------------------
left, right = st.columns([2.1, 1])
with left:
    fig = line_by_area(
        history, y="population", y_title="Persons", hover_format="%{y:,} persons", height=360
    )
    chart_card(
        f"Population of {primary.area_name}, {periods.iloc[0].period_label}–{latest.period_label}",
        fig,
        subtitle="Persons on the first day of each quarter",
        table=history[["period_label", "population", "yoy_change", "yoy_growth_pct"]]
        .rename(
            columns={
                "period_label": "Quarter",
                "population": "Population",
                "yoy_change": "YoY change",
                "yoy_growth_pct": "YoY growth (%)",
            }
        )
        .iloc[::-1],
        key="ov_trend",
    )
with right, st.container(border=True):
    st.html(
        '<div class="cdl-section">Data freshness</div>'
        '<div class="cdl-section-sub">Publication dates vs. pipeline execution</div>'
    )
    in_sync = (wh.snapshot_manifest or {}).get("content_sha256") == info["content_sha256"]
    facts(
        [
            (
                "Latest reporting period",
                f"{latest.period_label} (counted {fmt_date(latest.reference_date)})",
            ),
            (
                "Published by StatBank",
                f"{fmt_timestamp(info['source_updated_local'])} (Danish time)",
            ),
            ("Extracted from API", f"{fmt_timestamp(info['extracted_at_utc'])} UTC"),
            ("Warehouse built", f"{fmt_timestamp(info['built_at_utc'])} UTC"),
            ("Source table", f"{info['table_id']} — {info['table_title']}"),
            ("Snapshot", info["snapshot_version"]),
        ]
    )
    st.write("")
    if in_sync:
        st.success("Dashboard uses the latest downloaded snapshot.", icon=":material/check_circle:")
    else:
        st.warning(
            "Warehouse differs from the bundled snapshot — rebuild to sync.",
            icon=":material/warning:",
        )

# --- Row 2: growth + comparison ------------------------------------------------------------
left, right = st.columns(2)
with left:
    recent = history[history["period_index"] >= latest.period_index - 39]
    chart_card(
        "Annual population growth",
        growth_bars(recent, height=320),
        subtitle=f"{primary.area_name}, % change vs the same quarter a year earlier",
        table=recent[["period_label", "yoy_comparison_period_code", "yoy_growth_pct"]]
        .dropna()
        .rename(
            columns={
                "period_label": "Quarter",
                "yoy_comparison_period_code": "Compared with",
                "yoy_growth_pct": "YoY growth (%)",
            }
        )
        .iloc[::-1],
        note="Derived by Copenhagen Data Lab from official counts. Last 10 years shown.",
        key="ov_growth",
    )
with right:
    focus = focus_names(wh)
    codes = areas.loc[areas["area_name"].isin(focus), "area_code"].tolist()
    comp = wh.load("comparison", codes, latest.period_code)
    chart_card(
        "Largest Danish municipalities",
        ranked_bars(
            comp,
            value="population",
            value_format="{:,.0f}",
            highlight=primary.area_name,
            x_title="Persons",
            height=320,
        ),
        subtitle=f"Population, {latest.period_label}",
        table=comp[["area_name", "population", "yoy_growth_pct", "rank_population"]].rename(
            columns={
                "area_name": "Municipality",
                "population": "Population",
                "yoy_growth_pct": "YoY growth (%)",
                "rank_population": "Rank among 98 municipalities",
            }
        ),
        key="ov_comp",
    )

# --- Row 3: age distribution + summary table ------------------------------------------------
left, right = st.columns([1.15, 1])
with left:
    ages = wh.load(
        "age_group_shares", [primary.area_code, country.area_code], [latest.period_code], "TOT"
    )
    colors = {primary.area_name: SERIES[0], COUNTRY_NAME: REFERENCE}
    chart_card(
        "Age distribution",
        age_share_bars(ages, series_col="area_name", height=330, series_colors=colors),
        subtitle=f"Share of population by age group, {latest.period_label}",
        table=ages.pivot_table(
            index="age_group", columns="area_name", values="share_pct", sort=False
        )
        .round(2)
        .reset_index(),
        note="Age groups are summed from single-year ages; shares use the official total.",
        key="ov_age",
    )
with right, st.container(border=True):
    st.html(
        '<div class="cdl-section">Latest population summary</div>'
        f'<div class="cdl-section-sub">{latest.period_label} · official counts and derived '
        "growth</div>"
    )
    summary = wh.load("comparison", [*codes, country.area_code], latest.period_code)
    table = pd.DataFrame(
        {
            "Area": summary["area_name"],
            "Population": summary["population"].map(fmt_int),
            "YoY change": summary["yoy_change"].map(fmt_signed_int),
            "YoY growth": summary["yoy_growth_pct"].map(lambda v: fmt_pct(v, signed=True)),
            "Share of DK": summary["share_of_denmark_pct"].map(fmt_pct),
        }
    )
    st.dataframe(table, hide_index=True, height=250)
    st.caption(
        "Share of DK is not shown for All Denmark itself. Source: Statistics Denmark, "
        "FOLK1A; growth and shares calculated by Copenhagen Data Lab."
    )
