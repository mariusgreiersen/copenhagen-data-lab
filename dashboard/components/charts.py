"""Plotly chart builders. Every builder returns a styled figure; callers add the table view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from components.theme import (
    EARLIER,
    INK_SECONDARY,
    LATER,
    NEGATIVE,
    ORDINAL,
    POSITIVE,
    REFERENCE,
    SERIES,
    SEX_COLORS,
    area_colors,
    style_figure,
)


def line_by_area(
    frame: pd.DataFrame,
    *,
    y: str,
    y_title: str,
    hover_format: str,
    height: int = 380,
    end_labels: bool = True,
    reference_line: float | None = None,
    source: str | None = None,
    order: list[str] | None = None,
) -> go.Figure:
    """One line per area, x = reference date. Gaps in data stay gaps (no interpolation).

    ``order`` (area codes) sets the legend order, e.g. the user's selection order.
    """
    fig = go.Figure()
    names = list(dict.fromkeys(frame["area_name"]))
    if order:
        rank = {code: i for i, code in enumerate(order)}
        first = frame.drop_duplicates("area_name").set_index("area_name")["area_code"]
        names.sort(key=lambda n: rank.get(first[n], len(rank)))
    colors = area_colors(names)
    for name in names:
        part = frame[frame["area_name"] == name].sort_values("period_index")
        fig.add_trace(
            go.Scatter(
                x=part["reference_date"],
                y=part[y],
                name=name,
                mode="lines",
                line={
                    "width": 2.2,
                    "color": colors[name],
                    "dash": "dot" if name == "All Denmark" else "solid",
                },
                customdata=part[["period_label"]],
                hovertemplate=f"<b>{name}</b> · %{{customdata[0]}}<br>{hover_format}<extra></extra>",
                connectgaps=False,
            )
        )
        last = part.dropna(subset=[y]).tail(1)
        if end_labels and not last.empty and len(names) <= 4:
            fig.add_trace(
                go.Scatter(
                    x=last["reference_date"],
                    y=last[y],
                    mode="markers",
                    showlegend=False,
                    marker={
                        "size": 8,
                        "color": colors[name],
                        "line": {"width": 2, "color": "#ffffff"},
                    },
                    hoverinfo="skip",
                )
            )
    if reference_line is not None:
        fig.add_hline(y=reference_line, line_width=1, line_color="#9aa3b2")
    kwargs = {"source": source} if source is not None else {}
    # A single series is named by the chart title; a legend box would only repeat it.
    return style_figure(fig, height=height, y_title=y_title, legend=len(names) > 1, **kwargs)


def growth_bars(frame: pd.DataFrame, *, y: str = "yoy_growth_pct", height: int = 320) -> go.Figure:
    """Signed growth per quarter on a diverging blue/red pair around zero."""
    data = frame.dropna(subset=[y]).sort_values("period_index")
    colors = [POSITIVE if v >= 0 else NEGATIVE for v in data[y]]
    fig = go.Figure(
        go.Bar(
            x=data["reference_date"],
            y=data[y],
            marker={"color": colors, "cornerradius": 3},
            customdata=data[["period_label", "yoy_comparison_period_code"]],
            hovertemplate="<b>%{customdata[0]}</b><br>YoY growth: %{y:+.2f}%"
            "<br>vs %{customdata[1]}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_width=1, line_color="#9aa3b2")
    style_figure(fig, height=height, y_title="YoY growth (%)", legend=False, hovermode="closest")
    fig.update_yaxes(ticksuffix="%")
    return fig


def grouped_growth_bars(frame: pd.DataFrame, height: int = 360) -> go.Figure:
    fig = go.Figure()
    names = list(dict.fromkeys(frame["area_name"]))
    colors = area_colors(names)
    for name in names:
        part = frame[frame["area_name"] == name].sort_values("period_index")
        fig.add_trace(
            go.Bar(
                x=part["reference_date"],
                y=part["yoy_growth_pct"],
                name=name,
                marker={"color": colors[name], "cornerradius": 2},
                customdata=part[["period_label"]],
                hovertemplate=f"<b>{name}</b> · %{{customdata[0]}}<br>%{{y:+.2f}}%<extra></extra>",
            )
        )
    fig.add_hline(y=0, line_width=1, line_color="#9aa3b2")
    style_figure(fig, height=height, y_title="YoY growth (%)", hovermode="x unified")
    fig.update_layout(barmode="group", bargap=0.15)
    fig.update_yaxes(ticksuffix="%")
    return fig


def ranked_bars(
    frame: pd.DataFrame,
    *,
    value: str,
    value_format: str,
    highlight: str | None = None,
    x_title: str = "",
    height: int | None = None,
    suffix: str = "",
) -> go.Figure:
    """Horizontal bars, largest at top. One series → one colour; optional highlight."""
    data = frame.dropna(subset=[value]).sort_values(value)
    colors = [
        SERIES[0] if (highlight is None or n == highlight) else "#b9c3d1" for n in data["area_name"]
    ]
    if highlight is None:
        palette = area_colors(list(data["area_name"]))
        colors = [palette[n] for n in data["area_name"]]
    fig = go.Figure(
        go.Bar(
            x=data[value],
            y=data["area_name"],
            orientation="h",
            marker={"color": colors, "cornerradius": 4},
            text=[value_format.format(v) for v in data[value]],
            textposition="outside",
            textfont={"color": INK_SECONDARY, "size": 12},
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
        )
    )
    style_figure(
        fig,
        height=height or max(220, 46 * len(data) + 90),
        legend=False,
        x_title=x_title,
        hovermode="closest",
    )
    lo, hi = min(0.0, float(data[value].min())), max(0.0, float(data[value].max()))
    pad = (hi - lo) * 0.18 or 1.0  # room for outside labels so they are never clipped
    fig.update_xaxes(
        showgrid=True,
        gridcolor="#eef1f5",
        ticksuffix=suffix,
        range=[lo - (pad if lo < 0 else 0), hi + pad],
    )
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", tickfont={"color": "#1b2533", "size": 13})
    return fig


def age_share_bars(
    frame: pd.DataFrame,
    *,
    series_col: str,
    height: int = 340,
    series_colors: dict[str, str] | None = None,
) -> go.Figure:
    """Grouped horizontal bars of age-group shares (one bar group per age band)."""
    fig = go.Figure()
    order = (
        frame[["age_group", "age_group_order"]]
        .drop_duplicates()
        .sort_values("age_group_order", ascending=False)["age_group"]
        .tolist()
    )
    series = list(dict.fromkeys(frame[series_col]))
    colors = series_colors or area_colors(series)
    for name in reversed(series):
        part = frame[frame[series_col] == name].set_index("age_group").reindex(order)
        fig.add_trace(
            go.Bar(
                y=order,
                x=part["share_pct"],
                name=str(name),
                orientation="h",
                marker={"color": colors.get(name, REFERENCE), "cornerradius": 3},
                customdata=part[["population"]].to_numpy(),
                hovertemplate=f"<b>{name}</b> · %{{y}}<br>%{{x:.2f}}% · %{{customdata[0]:,}} persons"
                "<extra></extra>",
            )
        )
    style_figure(fig, height=height, x_title="Share of population (%)", hovermode="y unified")
    fig.update_layout(
        barmode="group", bargap=0.28, bargroupgap=0.06, legend={"traceorder": "reversed"}
    )
    fig.update_xaxes(showgrid=True, gridcolor="#eef1f5", ticksuffix="%")
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", tickfont={"color": "#1b2533", "size": 13})
    return fig


def age_group_columns(frame: pd.DataFrame, height: int = 320) -> go.Figure:
    """Age-group population for one area/period on the ordinal blue ramp (ordered bands)."""
    data = frame.sort_values("age_group_order")
    fig = go.Figure(
        go.Bar(
            x=data["age_group"],
            y=data["population"],
            marker={"color": ORDINAL[: len(data)], "cornerradius": 4},
            text=[f"{s:.1f}%" for s in data["share_pct"]],
            textposition="outside",
            textfont={"color": INK_SECONDARY},
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{y:,} persons · %{text}<extra></extra>",
        )
    )
    style_figure(fig, height=height, y_title="Persons", legend=False, hovermode="closest")
    return fig


def period_comparison_bars(
    frame: pd.DataFrame, earlier: str, later: str, height: int = 340
) -> go.Figure:
    data = frame.sort_values("age_group_order")
    fig = go.Figure()
    for label, color in ((earlier, EARLIER), (later, LATER)):
        part = data[data["period_label"] == label]
        fig.add_trace(
            go.Bar(
                x=part["age_group"],
                y=part["share_pct"],
                name=label,
                marker={"color": color, "cornerradius": 3},
                customdata=part[["population"]].to_numpy(),
                hovertemplate=f"<b>{label}</b> · %{{x}}<br>%{{y:.2f}}% · %{{customdata[0]:,}} persons"
                "<extra></extra>",
            )
        )
    style_figure(fig, height=height, y_title="Share of population (%)")
    fig.update_layout(barmode="group")
    fig.update_yaxes(ticksuffix="%")
    return fig


def population_pyramid(frame: pd.DataFrame, height: int = 520) -> go.Figure:
    """Single-year age by sex. Men drawn to the left (negated), women to the right."""
    fig = go.Figure()
    max_value = frame["population"].max()
    for sex, sign in (("Men", -1), ("Women", 1)):
        part = frame[frame["sex_label"] == sex]
        fig.add_trace(
            go.Bar(
                y=part["age_years"],
                x=sign * part["population"],
                name=sex,
                orientation="h",
                marker={"color": SEX_COLORS[sex], "line": {"width": 0}},
                customdata=part[["population"]].to_numpy(),
                hovertemplate=f"<b>{sex}</b>, age %{{y}}<br>%{{customdata[0]:,}} persons<extra></extra>",
            )
        )
    style_figure(
        fig, height=height, y_title="Age (years)", x_title="Persons", hovermode="y unified"
    )
    ticks = _nice_ticks(max_value)
    fig.update_layout(barmode="overlay", bargap=0.08)
    fig.update_xaxes(
        tickvals=[-t for t in ticks[::-1]] + ticks[1:],
        ticktext=[f"{t:,}" for t in ticks[::-1]] + [f"{t:,}" for t in ticks[1:]],
        showgrid=True,
        gridcolor="#eef1f5",
    )
    fig.update_yaxes(range=[-1, 101], dtick=10)
    return fig


def _nice_ticks(max_value: float) -> list[int]:
    if not max_value or max_value <= 0:
        return [0]
    raw = max_value / 3
    magnitude = 10 ** (len(str(int(raw))) - 1)
    step = max(1, int(round(raw / magnitude)) * magnitude)
    return list(range(0, int(max_value) + step, step))
