"""Pipeline Health — run status, freshness and data quality from recorded runs only."""

from __future__ import annotations

import json
from html import escape

import pandas as pd
import streamlit as st

from components.data import warehouse_or_stop
from components.layout import facts, page_header, section
from components.metrics import fmt_date, fmt_int, fmt_timestamp, kpi_card

wh = warehouse_or_stop()
info = wh.load("warehouse_info")
runs = wh.load("pipeline_runs")
quality = wh.load("quality_results")
manifest = info["manifest"]

page_header(
    "Pipeline Health",
    "Status of the ETL pipeline that produced the published data.",
    eyebrow="Operations",
)

st.caption(
    "Runs listed here are the ones recorded in this environment's run log "
    "(`data/runs/pipeline_runs.jsonl`). A fresh deployment only knows the run that built its "
    "warehouse from the bundled snapshot; the original API extraction is described by the "
    "snapshot manifest below. No runs are simulated."
)

latest_attempt = runs.iloc[0] if not runs.empty else None
successes = runs[runs["status"] == "success"]
latest_success = successes.iloc[0] if not successes.empty else None
summary = quality["status"].value_counts()

cols = st.columns(5)
with cols[0]:
    status = latest_attempt["status"] if latest_attempt is not None else "unknown"
    kpi_card(
        "Latest attempted run",
        status.capitalize(),
        delta=f"{latest_attempt['source_mode']} mode" if latest_attempt is not None else None,
        delta_direction="up" if status == "success" else "down",
        footnote=f"{fmt_timestamp(latest_attempt['started_at_utc'])} UTC"
        if latest_attempt is not None
        else "",
        kind="recorded",
    )
with cols[1]:
    kpi_card(
        "Latest successful run",
        fmt_date(latest_success["finished_at_utc"]) if latest_success is not None else "—",
        footnote=f"{pd.Timestamp(latest_success['finished_at_utc']):%H:%M} UTC · published "
        "this warehouse"
        if latest_success is not None
        else "",
        kind="recorded",
    )
with cols[2]:
    kpi_card(
        "Duration",
        f"{latest_success['duration_s']:.1f} s" if latest_success is not None else "—",
        footnote="Extract → publish, latest success",
        kind="recorded",
    )
with cols[3]:
    kpi_card(
        "Records processed",
        fmt_int(latest_success["records_extracted"]) if latest_success is not None else "—",
        footnote=f"{fmt_int(latest_success['records_staged'])} staged observations"
        if latest_success is not None
        else "",
        kind="recorded",
    )
with cols[4]:
    failed = int(summary.get("fail", 0))
    warned = int(summary.get("warn", 0))
    kpi_card(
        "Quality checks",
        f"{int(summary.get('pass', 0))} / {len(quality)} passed",
        delta=f"{failed} failed · {warned} warnings",
        delta_direction="up" if failed == 0 and warned == 0 else "down",
        footnote="For the published build",
        kind="recorded",
    )

# --- Stages -----------------------------------------------------------------------------
with st.container(border=True):
    section("Pipeline stages", "Latest attempted run")
    stages = json.loads(latest_attempt["stages_json"]) if latest_attempt is not None else []
    by_name = {s["name"]: s for s in stages}
    chips = []
    for name in ("extract", "validate", "transform", "load", "verify", "publish"):
        stage = by_name.get(name)
        css = "skip" if stage is None else ("ok" if stage["status"] == "success" else "bad")
        meta = "not reached" if stage is None else f"{stage['status']} · {stage['duration_s']:.2f}s"
        chips.append(
            f'<div class="cdl-stage {css}"><div class="cdl-stage-name">'
            f'{name.capitalize()}</div><div class="cdl-stage-meta">{escape(meta)}</div></div>'
        )
    st.html('<div class="cdl-stages">' + '<span class="cdl-arrow">→</span>'.join(chips) + "</div>")
    if latest_attempt is not None and latest_attempt["status"] != "success":
        st.error(
            f"Failed at **{latest_attempt['failed_stage']}**: {latest_attempt['error_message']}. "
            "The previously published warehouse was kept.",
            icon=":material/error:",
        )

# --- Freshness ----------------------------------------------------------------------------
left, right = st.columns([1, 1])
with left, st.container(border=True):
    section("Data freshness", "Statistical publication vs. pipeline execution")
    facts(
        [
            ("Latest source period", info["last_period"]),
            (
                "StatBank table updated",
                f"{fmt_timestamp(info['source_updated_local'])} (Danish time)",
            ),
            ("Last successful extraction", f"{fmt_timestamp(info['extracted_at_utc'])} UTC"),
            ("Snapshot published", f"{fmt_timestamp(manifest.get('published_at_utc'))} UTC"),
            ("Warehouse built", f"{fmt_timestamp(info['built_at_utc'])} UTC"),
            ("Built from", f"{info['source_mode']} source"),
        ]
    )
with right, st.container(border=True):
    section("Snapshot provenance", "Recorded when the data was downloaded")
    facts(
        [
            ("Extraction run", manifest["extraction"]["run_id"]),
            ("Snapshot version", info["snapshot_version"]),
            ("Records", fmt_int(manifest["record_count"])),
            ("Content SHA-256", info["content_sha256"][:20] + "…"),
            ("Transformation version", info["transformation_version"]),
            ("Pipeline version", info["pipeline_version"]),
        ]
    )

# --- Quality --------------------------------------------------------------------------------
with st.container(border=True):
    section(
        "Data quality report",
        "Raw-data checks (before transformation) and post-load verification (before publication)",
    )
    raw = quality[quality["stage"] == "raw"]
    missing = raw.loc[raw["check_id"] == "E", "invalid_records"].sum()
    dupes = raw.loc[raw["check_id"].isin(["D", "D2"]), "invalid_records"].sum()
    schema = raw.loc[raw["check_id"].isin(["A", "G"]), "invalid_records"].sum()
    c = st.columns(3)
    c[0].metric("Missing observations", fmt_int(missing), border=True)
    c[1].metric("Duplicate observations", fmt_int(dupes), border=True)
    c[2].metric("Schema / code issues", fmt_int(schema), border=True)
    icon = {"pass": "✅ pass", "warn": "⚠️ warning", "fail": "❌ fail"}
    table = quality.assign(status=quality["status"].map(icon))
    st.dataframe(
        table[
            [
                "check_id",
                "name",
                "stage",
                "severity",
                "status",
                "records_tested",
                "invalid_records",
                "explanation",
                "executed_at_utc",
            ]
        ],
        hide_index=True,
        height=420,
        column_config={
            "check_id": "ID",
            "name": "Check",
            "stage": "Stage",
            "severity": "Severity",
            "status": "Result",
            "records_tested": st.column_config.NumberColumn("Tested", format="localized"),
            "invalid_records": st.column_config.NumberColumn("Invalid", format="localized"),
            "explanation": st.column_config.TextColumn("Explanation", width="large"),
            "executed_at_utc": st.column_config.DatetimeColumn(
                "Executed (UTC)", format="YYYY-MM-DD HH:mm:ss"
            ),
        },
    )
    st.caption(
        "Critical failures stop the run before publication; warnings are recorded and shown."
    )

# --- Run history ------------------------------------------------------------------------------
with st.container(border=True):
    section("Run history", f"{len(runs)} recorded run(s), newest first")
    hist = runs[
        [
            "run_id",
            "source_mode",
            "status",
            "started_at_utc",
            "duration_s",
            "records_extracted",
            "checks_passed",
            "checks_warned",
            "checks_failed",
            "failed_stage",
            "error_message",
            "published",
        ]
    ]
    st.dataframe(
        pd.DataFrame(hist),
        hide_index=True,
        column_config={
            "run_id": "Run ID",
            "source_mode": "Source",
            "status": "Status",
            "started_at_utc": st.column_config.DatetimeColumn(
                "Started (UTC)", format="YYYY-MM-DD HH:mm"
            ),
            "duration_s": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
            "records_extracted": st.column_config.NumberColumn("Records", format="localized"),
            "checks_passed": "Passed",
            "checks_warned": "Warnings",
            "checks_failed": "Failed",
            "failed_stage": "Failed stage",
            "error_message": "Error",
            "published": "Published",
        },
    )

with st.container(border=True):
    section("Run the pipeline locally")
    st.code(
        "python -m copenhagen_data_lab.pipeline --source snapshot   # offline rebuild\n"
        "python -m copenhagen_data_lab.pipeline --source api        # refresh from StatBank",
        language="bash",
    )
    st.caption(
        "Refreshes run from the command line or the scheduled GitHub Actions workflow; "
        "the public dashboard cannot trigger downloads."
    )
