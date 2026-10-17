"""Demographics — age and sex composition of Denmark and the focus municipalities."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.charts import (
    age_group_columns,
    age_share_bars,
    period_comparison_bars,
    population_pyramid,
)
from components.data import warehouse_or_stop
from components.filters import period_select, single_area_select
from components.layout import chart_card, page_header
from components.metrics import NA, fmt_int, fmt_pct, kpi_card
from components.theme import COUNTRY_NAME, area_colors

wh = warehouse_or_stop()
periods = wh.load("periods")
areas = wh.load("areas")
country = areas[areas["area_level"] == "country"].iloc[0]

page_header("Demographics", "Age and sex composition from single-year official counts.")

SEX_OPTIONS = {"Total": "TOT", "Men": "1", "Women": "2"}
with st.container(border=True):
    c1, c2, c3, c4 = st.columns([1.4, 1, 1, 1.2])
    with c1:
        area_code, area_name = single_area_select(wh, "Area", key="dm_area", only_age_detail=True)
    with c2:
        period_code, period_label = period_select(wh, "Reporting period", key="dm_period")
    with c3:
        sex_name = st.segmented_control(
            "Sex", list(SEX_OPTIONS), default="Total", key="dm_sex", required=True
        )
    with c4:
        idx = periods.loc[periods["period_code"] == period_code, "period_index"].item()
        same_quarter = periods[
            (periods["period_index"] < idx) & ((idx - periods["period_index"]) % 4 == 0)
        ]
        default_cmp = (
            same_quarter[same_quarter["period_index"] <= idx - 40]["period_label"].tolist()
            or same_quarter["period_label"].tolist()
            or [None]
        )[-1]
        compare_code, compare_label = period_select(
            wh,
            "Compare with",
            key="dm_compare",
            default=default_cmp,
            help="An earlier quarter for the age-distribution comparison. The same quarter of "
            "an earlier year avoids seasonal effects.",
        )
st.caption(
    "Single-year age detail is extracted for All Denmark and the five focus "
    "municipalities: Copenhagen, Aarhus, Odense, Aalborg and Frederiksberg."
)
sex_code = SEX_OPTIONS[sex_name]

# --- KPIs -----------------------------------------------------------------------------------
split = wh.load("sex_split", area_code, period_code)
singles = wh.load("single_year_ages", area_code, period_code)
by_sex = dict(zip(split["sex_label"], split["population"], strict=True))
total = by_sex.get("Total")


def median_age(frame: pd.DataFrame) -> float | None:
    """Median age in completed years: first age where the cumulative count reaches 50%."""
    if frame.empty or frame["population"].isna().any():
        return None
    counts = frame.groupby("age_years")["population"].sum().sort_index()
    cumulative = counts.cumsum()
    return float(cumulative[cumulative >= counts.sum() / 2].index[0])


subset = singles if sex_name == "Total" else singles[singles["sex_label"] == sex_name]
cols = st.columns(4)
with cols[0]:
    kpi_card(
        f"Population ({sex_name.lower()})",
        fmt_int(by_sex.get(sex_name)),
        footnote=f"{area_name}, {period_label}",
        kind="official",
    )
with cols[1]:
    men = by_sex.get("Men")
    kpi_card(
        "Men",
        fmt_int(men),
        footnote=f"{fmt_pct(100 * men / total, 1)} of total" if men is not None and total else "",
        kind="official",
    )
with cols[2]:
    women = by_sex.get("Women")
    kpi_card(
        "Women",
        fmt_int(women),
        footnote=f"{fmt_pct(100 * women / total, 1)} of total"
        if women is not None and total
        else "",
        kind="official",
    )
with cols[3]:
    med = median_age(subset)
    kpi_card(
        f"Median age ({sex_name.lower()})",
        NA if med is None else f"{med:.0f} years",
        footnote="From single-year counts",
        kind="derived",
    )
st.write("")

# --- Age groups + pyramid -----------------------------------------------------------------
groups = wh.load("age_group_shares", [area_code], [period_code], sex_code)
left, right = st.columns([1, 1.15])
with left:
    chart_card(
        "Population by age group",
        age_group_columns(groups, height=420) if not groups.empty else None,
        subtitle=f"{area_name}, {sex_name.lower()}, {period_label} — label = share of total",
        table=groups[["age_group", "population", "share_pct"]].rename(
            columns={"age_group": "Age group", "population": "Persons", "share_pct": "Share (%)"}
        ),
        note="Derived: bands are sums of single-year official counts. The official "
        "'Age, total' category is never added to its own components.",
        key="dm_groups",
    )
with right:
    chart_card(
        "Population by single year of age",
        population_pyramid(singles, height=420) if not singles.empty else None,
        subtitle=f"{area_name}, men (left) and women (right), {period_label}",
        table=singles.pivot_table(index="age_years", columns="sex_label", values="population")
        .reset_index()
        .rename(columns={"age_years": "Age"}),
        note="Official counts for ages 0–100 shown; StatBank publishes ages up to 125.",
        key="dm_pyramid",
    )

# --- Comparison with Denmark + over time ----------------------------------------------------
left, right = st.columns(2)
with left:
    codes = [area_code] if area_code == country.area_code else [area_code, country.area_code]
    vs_dk = wh.load("age_group_shares", codes, [period_code], sex_code)
    colors = area_colors([area_name, COUNTRY_NAME])
    chart_card(
        f"{area_name} compared with Denmark",
        age_share_bars(vs_dk, series_col="area_name", height=360, series_colors=colors),
        subtitle=f"Share of population by age group, {sex_name.lower()}, {period_label}",
        table=vs_dk.pivot_table(
            index="age_group", columns="area_name", values="share_pct", sort=False
        )
        .round(2)
        .reset_index(),
        key="dm_vs_dk",
    )
with right:
    if compare_code == period_code:
        chart_card(
            "Change in age distribution",
            None,
            key="dm_change",
            empty_message="Choose a different comparison quarter to see the change.",
        )
    else:
        both = wh.load("age_group_shares", [area_code], [compare_code, period_code], sex_code)
        ordered = sorted(
            [(compare_label, compare_code), (period_label, period_code)],
            key=lambda p: periods.loc[periods["period_code"] == p[1], "period_index"].item(),
        )
        earlier, later = ordered[0][0], ordered[1][0]
        pivot = both.pivot_table(
            index=["age_group_order", "age_group"], columns="period_label", values="share_pct"
        ).reset_index()
        pivot["Change (pp)"] = pivot[later] - pivot[earlier]
        chart_card(
            "Change in age distribution",
            period_comparison_bars(both, earlier, later, height=360),
            subtitle=f"{area_name}, {sex_name.lower()}: {earlier} vs {later}",
            table=pivot.drop(columns="age_group_order")
            .round(2)
            .rename(columns={"age_group": "Age group"}),
            note="Differences between two shares are percentage points (pp), not percent change.",
            key="dm_change",
        )

with st.expander("What do these figures represent?", icon=":material/help:"):
    st.markdown(
        """
- **Population** is the number of residents registered in the area on the first day of the
  quarter (StatBank table FOLK1A), for the official sex categories *Men* and *Women*.
- **Age groups** (0–17, 18–29, 30–44, 45–64, 65+) are built by Copenhagen Data Lab by summing
  verified single-year age codes. A group is shown as unavailable if any single year is missing.
- **Shares** divide by the official *Age, total* count for the same area, quarter and sex.
  Quality check H2 verifies that the single years add up exactly to that total.
- **Median age** is the first age at which the cumulative count reaches half the population.
- In comparisons, grey always marks the national reference (All Denmark).
"""
    )
