"""Phase 6 CLI: analyze a screenshot for advertisements (no emulator control).

Examples::

    python -m app.main --detect-ad --image tmp/screenshots/shot.png
    python -m app.main --detect-ad --image shot.png --provider openai --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.core.logging import setup_logging
from app.modules.ad_detection import ProviderNotConfiguredError, build_ad_detector

logger = logging.getLogger("detect_ad_cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main --detect-ad",
        description="Detect advertisements in a screenshot (Phase 6).",
    )
    parser.add_argument("--detect-ad", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--image", required=True, help="Path to a PNG/JPEG screenshot.")
    parser.add_argument(
        "--provider",
        default=None,
        help="heuristic|openai|gemini|claude|local|object_detection (default from settings).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument("--all", action="store_true", help="Emit every detection, not just primary.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def run_detect_ad_cli(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    path = Path(args.image)
    if not path.is_file():
        print(f"ERROR image not found: {path}", file=sys.stderr)
        return 2

    try:
        detector = build_ad_detector(args.provider)
        if args.all:
            results = [item.to_dict() for item in detector.detect_all(path)]
            payload: dict | list = results
        else:
            payload = detector.detect(path).to_dict()
    except ProviderNotConfiguredError as exc:
        logger.error("%s", exc)
        print(f"ERROR [PROVIDER] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.exception("detect-ad failed")
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    if args.json or isinstance(payload, list):
        print(json.dumps(payload, indent=2))
        return 0

    assert isinstance(payload, dict)
    print("\nAd detection (Phase 6)")
    print(f"  provider                 {payload.get('provider')}")
    print(f"  detected                 {payload.get('detected')}")
    print(f"  type                     {payload.get('type')}")
    print(f"  confidence               {payload.get('confidence')}")
    print(f"  position                 {payload.get('position')}")
    box = payload.get("bounding_box")
    if box:
        print(
            f"  bounding_box             x={box['x']} y={box['y']} "
            f"w={box['width']} h={box['height']}"
        )
    else:
        print("  bounding_box             (none)")
    evidence = payload.get("evidence") or []
    if evidence:
        print("  evidence")
        for item in evidence:
            print(f"    - {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_detect_ad_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
