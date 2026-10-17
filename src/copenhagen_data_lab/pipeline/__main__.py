"""Command-line entry point.

    python -m copenhagen_data_lab.pipeline --source snapshot   # offline, from data/snapshot
    python -m copenhagen_data_lab.pipeline --source api        # live StatBank refresh

Exit code 0 on success, 1 when any stage or critical quality check fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.run import run_pipeline
from copenhagen_data_lab.utils.logging import configure_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m copenhagen_data_lab.pipeline",
        description="Build the Copenhagen Data Lab warehouse from StatBank FOLK1A data.",
    )
    parser.add_argument(
        "--source",
        choices=["api", "snapshot"],
        required=True,
        help="'api' downloads from StatBank; 'snapshot' uses data/snapshot offline",
    )
    parser.add_argument("--data-dir", type=Path, help="Override the data directory")
    parser.add_argument("--first-period", help="First quarter to extract, e.g. 2015K1 (api mode)")
    parser.add_argument("--last-period", help="Last quarter to extract (api mode)")
    parser.add_argument(
        "--no-snapshot-update",
        action="store_true",
        help="In api mode, build the warehouse but leave data/snapshot untouched",
    )
    parser.add_argument("--log-json", action="store_true", help="Emit JSON log lines")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(as_json=args.log_json or None)
    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
    if args.first_period:
        overrides["first_period"] = args.first_period
    if args.last_period:
        overrides["last_period"] = args.last_period
    settings = Settings.from_env(**overrides)

    record = run_pipeline(args.source, settings, update_snapshot=not args.no_snapshot_update)

    print(f"\nRun {record.run_id}: {record.status.upper()} in {record.duration_s:.1f}s")
    for stage in record.stages:
        print(f"  {stage['name']:<10} {stage['status']:<8} {stage['duration_s']:>7.2f}s")
    print(
        f"  checks: {record.checks_passed} passed, {record.checks_warned} warnings, "
        f"{record.checks_failed} failed"
    )
    for check in record.checks:
        if check["status"] != "pass":
            print(
                f"    [{check['status'].upper()}] {check['check_id']} {check['name']}: "
                f"{check['explanation']}"
            )
    if record.status == "success":
        print(
            f"  snapshot: {record.snapshot_version}"
            f"{' (updated)' if record.snapshot_updated else ''}"
        )
        print(f"  warehouse: {settings.warehouse_path}")
        return 0
    print(f"  failed at stage '{record.failed_stage}': {record.error_message}", file=sys.stderr)
    print("  The previously published warehouse and snapshot were left unchanged.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
