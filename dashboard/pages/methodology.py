"""About & Methodology — renders docs/methodology.md plus live provenance."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.data import warehouse_or_stop
from components.layout import facts, page_header
from components.metrics import fmt_timestamp

wh = warehouse_or_stop()
info = wh.load("warehouse_info")
manifest = info["manifest"]

page_header(
    "About & Methodology",
    "How official statistics become the figures on this dashboard.",
    eyebrow="Documentation",
)

with st.container(border=True):
    st.html('<div class="cdl-section">Source and attribution</div>')
    facts(
        [
            ("Provider", info["provider"]),
            ("Table", f"{info['table_id']} — {info['table_title']}"),
            ("Periods", f"{info['first_period']} – {info['last_period']}"),
            (
                "Table updated by StatBank",
                f"{fmt_timestamp(info['source_updated_local'])} (Danish time)",
            ),
            ("Snapshot", info["snapshot_version"]),
            ("Licence", manifest["licence"]["name"]),
        ]
    )
    st.markdown(
        f"**Source: Statistics Denmark.** Data from [StatBank table {info['table_id']}]"
        f"(https://www.statbank.dk/{info['table_id']}) via the [StatBank API]"
        f"(https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api). "
        f"[Terms of reuse]({manifest['licence']['url']}). Growth rates, shares, indices, age "
        "groups, ranks and median ages are **calculated by Copenhagen Data Lab** and are not "
        "figures published by Statistics Denmark."
    )

doc = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"
if doc.exists():
    with st.container(border=True):
        st.markdown(doc.read_text(encoding="utf-8"))
else:
    st.info("docs/methodology.md not found.")
