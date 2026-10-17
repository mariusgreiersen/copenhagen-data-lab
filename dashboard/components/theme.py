"""Visual tokens, entity colours and the shared Plotly layout.

Categorical colours follow the *entity*, never its position in a selection: Copenhagen is
always slot 1 blue, Aarhus slot 2 orange, and so on. The order is the validated default
palette (adjacent CVD ΔE ≥ 9.1 on white). Three slots fall below 3:1 contrast on white,
so every chart also ships direct end labels or a data-table view.
"""

from __future__ import annotations

from collections.abc import Sequence

import plotly.graph_objects as go
import streamlit as st

# Ink & chrome
INK = "#1b2533"
INK_SECONDARY = "#4a5568"
MUTED = "#7a8494"
GRID = "#e8ebf0"
AXIS = "#c5cbd5"
SURFACE = "#ffffff"
NAVY = "#0f1e33"

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
REFERENCE = "#5b6575"  # All Denmark: neutral reference ink, not a categorical hue
POSITIVE = "#2a78d6"  # diverging pair for signed growth (blue ↔ red)
NEGATIVE = "#e34948"
ORDINAL = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]  # validated --ordinal
EARLIER, LATER = "#86b6ef", "#1c5cab"
SEX_COLORS = {"Men": "#2a78d6", "Women": "#eb6834"}

FOCUS_ORDER = ["Copenhagen", "Aarhus", "Odense", "Aalborg", "Frederiksberg"]
COUNTRY_NAME = "All Denmark"
MAX_SERIES = 8
FONT = "Inter, -apple-system, 'Segoe UI', sans-serif"
SOURCE_NOTE = "Source: Statistics Denmark, StatBank FOLK1A"


def area_colors(names: Sequence[str]) -> dict[str, str]:
    """Stable colour per area name. Non-focus areas take the remaining slots in order."""
    colors: dict[str, str] = {}
    spare = iter(SERIES[len(FOCUS_ORDER) :])
    for name in names:
        if name == COUNTRY_NAME:
            colors[name] = REFERENCE
        elif name in FOCUS_ORDER:
            colors[name] = SERIES[FOCUS_ORDER.index(name)]
        else:
            colors[name] = next(spare, MUTED)
    return colors


def style_figure(
    fig: go.Figure,
    *,
    height: int = 360,
    y_title: str | None = None,
    x_title: str | None = None,
    source: str | None = SOURCE_NOTE,
    legend: bool = True,
    hovermode: str = "x unified",
) -> go.Figure:
    fig.update_layout(
        template="none",
        height=height,
        font={"family": FONT, "size": 13, "color": INK},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={
            "l": 8,
            "r": 24,
            "t": 36 if legend else 12,
            "b": (76 if source else 32) + (20 if x_title else 0),
        },
        hovermode=hovermode,
        hoverlabel={
            "bgcolor": SURFACE,
            "bordercolor": AXIS,
            "font": {"family": FONT, "size": 12, "color": INK},
        },
        showlegend=legend,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "title": None,
            "font": {"size": 12, "color": INK_SECONDARY},
        },
        bargap=0.25,
        bargroupgap=0.08,
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=AXIS,
        tickcolor=AXIS,
        ticks="outside",
        ticklen=4,
        tickfont={"color": MUTED, "size": 12},
        title=x_title,
        title_font={"color": INK_SECONDARY, "size": 12},
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=GRID,
        zeroline=False,
        linecolor="rgba(0,0,0,0)",
        tickfont={"color": MUTED, "size": 12},
        title=y_title,
        title_font={"color": INK_SECONDARY, "size": 12},
        automargin=True,
    )
    if source:
        fig.add_annotation(
            text=source,
            xref="paper",
            yref="paper",
            x=0,
            y=0,
            yshift=-40 - (22 if x_title else 0),
            xanchor="left",
            yanchor="top",
            showarrow=False,
            font={"size": 11, "color": MUTED},
        )
    return fig


CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1380px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; color: {INK}; }}

.cdl-header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:1rem;
               flex-wrap:wrap; margin-bottom:1.2rem; }}
.cdl-eyebrow {{ font-size:.78rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase;
                color:#1d5fae; margin-bottom:.25rem; }}
.cdl-title {{ font-size:2rem; font-weight:700; color:{INK}; line-height:1.15; margin:0; }}
.cdl-subtitle {{ font-size:1.02rem; color:{INK_SECONDARY}; margin-top:.35rem; }}
.cdl-source {{ display:inline-flex; align-items:center; gap:.45rem; font-size:.8rem;
               color:{INK_SECONDARY}; background:{SURFACE}; border:1px solid #dfe4ec;
               border-radius:999px; padding:.35rem .8rem; white-space:nowrap; }}
.cdl-source b {{ color:{INK}; font-weight:600; }}
.cdl-dot {{ width:.5rem; height:.5rem; border-radius:50%; background:#1baf7a; display:inline-block; }}

.cdl-kpi {{ background:{SURFACE}; border:1px solid #dfe4ec; border-radius:14px;
            padding:1rem 1.1rem .9rem; height:100%; min-height:176px;
            box-shadow:0 1px 2px rgba(15,30,51,.04); }}
.cdl-kpi-label {{ font-size:.8rem; font-weight:600; color:{INK_SECONDARY}; }}
.cdl-kpi-value {{ font-size:1.75rem; font-weight:700; color:{INK}; margin:.3rem 0 .2rem;
                  line-height:1.15; }}
.cdl-kpi-value.na {{ color:{MUTED}; font-size:1.2rem; font-weight:600; }}
.cdl-kpi-delta {{ font-size:.82rem; font-weight:600; }}
.cdl-kpi-delta.up {{ color:#1e6b3a; }}
.cdl-kpi-delta.down {{ color:#b42a2a; }}
.cdl-kpi-delta.flat {{ color:{INK_SECONDARY}; }}
.cdl-kpi-foot {{ font-size:.74rem; color:{MUTED}; margin-top:.45rem; display:flex; gap:.4rem;
                 align-items:center; flex-wrap:wrap; }}
.cdl-tag {{ font-size:.66rem; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
            border-radius:6px; padding:.12rem .4rem; }}
.cdl-tag.official {{ background:#e7f0fb; color:#1d4f91; }}
.cdl-tag.derived {{ background:#f1edfb; color:#4b3aa8; }}
.cdl-tag.recorded {{ background:#e9f6f0; color:#1e6b3a; }}

.cdl-section {{ font-size:1.05rem; font-weight:650; color:{INK}; margin:.2rem 0 .1rem; }}
.cdl-section-sub {{ font-size:.85rem; color:{INK_SECONDARY}; margin-bottom:.4rem; }}

.cdl-stages {{ display:flex; align-items:center; gap:.35rem; flex-wrap:wrap; margin:.3rem 0 .6rem; }}
.cdl-stage {{ background:{SURFACE}; border:1px solid #dfe4ec; border-radius:10px; padding:.55rem .8rem;
              min-width:112px; }}
.cdl-stage-name {{ font-size:.82rem; font-weight:650; color:{INK}; }}
.cdl-stage-meta {{ font-size:.72rem; color:{MUTED}; }}
.cdl-stage.ok {{ border-left:4px solid #0ca30c; }}
.cdl-stage.bad {{ border-left:4px solid #d03b3b; }}
.cdl-stage.skip {{ border-left:4px solid {AXIS}; }}
.cdl-arrow {{ color:{MUTED}; font-size:1rem; }}

.cdl-facts {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:.6rem 1.2rem; }}
.cdl-fact-label {{ font-size:.72rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em;
                   color:{MUTED}; }}
.cdl-fact-value {{ font-size:.92rem; color:{INK}; font-weight:500; word-break:break-word; }}

[data-testid="stSidebar"] .cdl-side-note {{ font-size:.78rem; color:#b8c4d6; line-height:1.45; }}
[data-testid="stSidebar"] .cdl-side-note b {{ color:#ffffff; font-weight:600; }}
[data-testid="stSidebar"] .cdl-side-note a {{ color:#9cc3f5; }}
</style>
"""


def inject_css() -> None:
    st.html(CSS)
