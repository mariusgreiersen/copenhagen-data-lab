"""Copenhagen Data Lab — Streamlit entry point.

    streamlit run dashboard/app.py

The app only reads the published DuckDB warehouse; it never calls the StatBank API.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if importlib.util.find_spec("copenhagen_data_lab") is None:  # running from a plain checkout
    sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="Copenhagen Data Lab",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from components.data import warehouse_or_stop  # noqa: E402
from components.theme import inject_css  # noqa: E402

inject_css()
st.logo(
    str(ROOT / "dashboard" / "assets" / "logo.svg"),
    size="large",
    icon_image=str(ROOT / "dashboard" / "assets" / "icon.svg"),
)

PAGES = Path(__file__).parent / "pages"
navigation = st.navigation(
    {
        "Analytics": [
            st.Page(
                PAGES / "overview.py",
                title="Overview",
                icon=":material/space_dashboard:",
                default=True,
            ),
            st.Page(
                PAGES / "population.py",
                title="Population Trends",
                icon=":material/show_chart:",
                url_path="population-trends",
            ),
            st.Page(PAGES / "demographics.py", title="Demographics", icon=":material/groups:"),
            st.Page(
                PAGES / "comparison.py",
                title="Municipality Comparison",
                icon=":material/compare_arrows:",
                url_path="comparison",
            ),
        ],
        "Data & operations": [
            st.Page(PAGES / "explorer.py", title="Data Explorer", icon=":material/table_view:"),
            st.Page(
                PAGES / "pipeline_health.py",
                title="Pipeline Health",
                icon=":material/monitor_heart:",
                url_path="pipeline-health",
            ),
            st.Page(
                PAGES / "methodology.py",
                title="About & Methodology",
                icon=":material/menu_book:",
                url_path="methodology",
            ),
        ],
    }
)

wh = warehouse_or_stop()
info = wh.load("warehouse_info")
with st.sidebar:
    st.html(
        f"""<div class="cdl-side-note">
            <b>Statistics Denmark — StatBank</b><br>
            Table <a href="https://www.statbank.dk/{info["table_id"]}" target="_blank">{info["table_id"]}</a>
            · {info["first_period"]}–{info["last_period"]}<br>
            Snapshot <code>{info["snapshot_version"]}</code><br><br>
            Official quarterly statistics, not real-time data. Derived metrics are
            calculated by Copenhagen Data Lab.
        </div>"""
    )

navigation.run()
