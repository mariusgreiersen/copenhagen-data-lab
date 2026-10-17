"""Page scaffolding: headers, source badge, chart cards with table views, empty states."""

from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


def page_header(
    title: str,
    subtitle: str,
    eyebrow: str = "Copenhagen Data Lab",
    source: str = "Statistics Denmark — StatBank",
) -> None:
    st.html(
        f"""<div class="cdl-header">
              <div>
                <div class="cdl-eyebrow">{escape(eyebrow)}</div>
                <h1 class="cdl-title">{escape(title)}</h1>
                <div class="cdl-subtitle">{escape(subtitle)}</div>
              </div>
              <div class="cdl-source"><span class="cdl-dot"></span>Source: <b>{escape(source)}</b></div>
            </div>"""
    )


def section(title: str, subtitle: str | None = None) -> None:
    sub = f'<div class="cdl-section-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.html(f'<div class="cdl-section">{escape(title)}</div>{sub}')


def chart_card(
    title: str,
    fig: go.Figure | None,
    *,
    subtitle: str | None = None,
    table: pd.DataFrame | None = None,
    note: str | None = None,
    key: str,
    empty_message: str = "No data for the current selection.",
) -> None:
    with st.container(border=True):
        section(title, subtitle)
        if fig is None:
            st.info(empty_message, icon=":material/info:")
            return
        st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)
        if note:
            st.caption(note)
        if table is not None:
            with st.expander("View data table", icon=":material/table_view:"):
                st.dataframe(table, hide_index=True)


def facts(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div><div class="cdl-fact-label">{escape(k)}</div>'
        f'<div class="cdl-fact-value">{escape(v)}</div></div>'
        for k, v in items
    )
    st.html(f'<div class="cdl-facts">{cells}</div>')


def csv_download(
    frame: pd.DataFrame, filename: str, label: str = "Download CSV", key: str | None = None
) -> None:
    st.download_button(
        label,
        frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        icon=":material/download:",
        key=key,
    )
