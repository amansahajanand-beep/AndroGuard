"""Phase 4/5 CLI: deterministic exploration (+ optional ad-placement campaign).

Examples::

    python -m app.main --explore --package com.example.app
    python -m app.main --explore-ads --package com.example.app --max-runs 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.core.logging import setup_logging
from app.modules.exploration.adb import AndroidADB, find_adb
from app.modules.exploration.ad_discovery import AdDiscoveryLimits
from app.modules.exploration.ad_explorer import run_ad_exploration
from app.modules.exploration.errors import AdbUnavailableError, ExplorationError
from app.modules.exploration.explorer import ExplorationLimits, run_exploration

logger = logging.getLogger("explore_cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main --explore|--explore-ads",
        description="Deterministic UI exploration (Phase 4) and ad placement discovery (Phase 5).",
    )
    parser.add_argument("--explore", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--explore-ads", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--serial", help="adb device serial.")
    parser.add_argument("--package", help="Target package (required without --analysis).")
    parser.add_argument("--activity", help="Optional launch activity.")
    parser.add_argument(
        "--analysis",
        help="Path to existing APK analysis JSON (uses activities/package as prior knowledge).",
    )
    parser.add_argument("--out-dir", help="Screenshot output directory.")
    parser.add_argument("--max-actions", type=int, default=None)
    parser.add_argument("--max-time", type=int, default=None, help="Seconds per run.")
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--max-states", type=int, default=None)
    parser.add_argument("--target-per-page", type=int, default=None)
    parser.add_argument("--max-runs", type=int, default=None, help="Phase 5: MAX_EXPLORATION_RUNS.")
    parser.add_argument(
        "--target-ad-per-page",
        type=int,
        default=None,
        help="Phase 5: TARGET_AD_VARIATIONS_PER_PAGE.",
    )
    parser.add_argument(
        "--max-ad-per-page",
        type=int,
        default=None,
        help="Phase 5: MAX_AD_VARIATIONS_PER_PAGE.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _load_analysis(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Analysis JSON must be an object.")
    return data


def _print(label: str, value: object) -> None:
    print(f"  {label:<24} {value}")


def _bind_adb(serial: str | None) -> AndroidADB:
    if find_adb() is None:
        raise AdbUnavailableError("adb was not found. Set ADB_PATH or ANDROID_SDK_ROOT.")
    base = AndroidADB()
    return base.for_serial(base.pick_device(serial))


def _limits_from_args(args: argparse.Namespace) -> ExplorationLimits:
    limits = ExplorationLimits.from_settings()
    if args.max_actions is not None:
        limits.max_actions = args.max_actions
    if args.max_time is not None:
        limits.max_time_seconds = args.max_time
    if args.max_depth is not None:
        limits.max_depth = args.max_depth
    if args.max_states is not None:
        limits.max_unique_states = args.max_states
    if args.target_per_page is not None:
        limits.target_states_per_page = args.target_per_page
    return limits


def cmd_explore(args: argparse.Namespace) -> int:
    analysis = _load_analysis(args.analysis) if args.analysis else None
    if analysis is None and not args.package:
        print("Provide --package or --analysis.", file=sys.stderr)
        return 2

    adb = _bind_adb(args.serial)
    session = run_exploration(
        adb,
        analysis=analysis,
        package_name=args.package,
        activity=args.activity,
        limits=_limits_from_args(args),
        output_dir=args.out_dir,
    )
    payload = session.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if session.status != "failed" else 1

    print("\nExploration (Phase 4)")
    _print("status", session.status)
    _print("stop reason", session.stop_reason)
    _print("package", session.package_name)
    _print("launch activity", session.launch_activity)
    _print("unique states", session.unique_states)
    _print("screenshots", session.screenshots_captured)
    _print("actions", session.actions_performed)
    _print("duration_ms", session.duration_ms)
    _print("max depth", session.graph.max_depth())
    print("\nNavigation tree")
    print(session.graph.ascii_tree())
    if session.warnings:
        print("\nWarnings")
        for warning in session.warnings:
            print(f"  - {warning}")
    return 0 if session.status != "failed" else 1


def cmd_explore_ads(args: argparse.Namespace) -> int:
    analysis = _load_analysis(args.analysis) if args.analysis else None
    if analysis is None and not args.package:
        print("Provide --package or --analysis.", file=sys.stderr)
        return 2

    adb = _bind_adb(args.serial)
    ad_limits = AdDiscoveryLimits.from_settings()
    if args.max_runs is not None:
        ad_limits.max_exploration_runs = args.max_runs
    if args.target_ad_per_page is not None:
        ad_limits.target_ad_variations_per_page = args.target_ad_per_page
    if args.max_ad_per_page is not None:
        ad_limits.max_ad_variations_per_page = args.max_ad_per_page

    campaign = run_ad_exploration(
        adb,
        analysis=analysis,
        package_name=args.package,
        activity=args.activity,
        limits=_limits_from_args(args),
        ad_limits=ad_limits,
        output_dir=args.out_dir,
        max_runs=args.max_runs,
    )
    payload = campaign.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if campaign.status != "failed" else 1

    print("\nAd placement exploration (Phase 5)")
    _print("status", campaign.status)
    _print("stop reason", campaign.stop_reason)
    _print("package", campaign.package_name)
    _print("runs", campaign.runs_completed)
    _print("unique ads", campaign.unique_ad_placements)
    _print("duration_ms", campaign.duration_ms)
    print("\nPlacements")
    if not campaign.catalog.placements:
        print("  (none detected)")
    for record in campaign.catalog.placements:
        fp = record.fingerprint
        print(
            f"  - page={fp.page} type={fp.ad_type} pos={fp.position} "
            f"bbox={list(fp.relative_bbox)} trigger={fp.trigger_action} "
            f"seen={record.seen_count}"
        )
    if campaign.warnings:
        print("\nWarnings")
        for warning in campaign.warnings:
            print(f"  - {warning}")
    return 0 if campaign.status != "failed" else 1


def run_explore_cli(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        if args.explore_ads:
            return cmd_explore_ads(args)
        return cmd_explore(args)
    except ExplorationError as exc:
        logger.error("%s: %s", exc.code, exc.message)
        print(f"ERROR [{exc.code}] {exc.message}", file=sys.stderr)
        return 1
    except Exception:
        logger.exception("explore CLI failed")
        raise


def main(argv: list[str] | None = None) -> int:
    return run_explore_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
