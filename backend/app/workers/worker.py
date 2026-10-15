"""CLI entry for Phase 12I exploration workers.

The API process embeds the worker pool by default. This module documents the
standalone entrypoint and can be used for health dumps:

    python -m app.workers.worker --health
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from app.workers.pool import get_worker_pool
from app.workers.registry import get_worker_registry

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AndroGuard exploration worker")
    parser.add_argument("--health", action="store_true", help="Print worker pool health JSON")
    parser.add_argument("--drain", action="store_true", help="Drain pool (stop accepting jobs)")
    parser.add_argument("--watch", type=float, default=0, help="Watch health for N seconds")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    pool = get_worker_pool()

    if args.drain:
        pool.drain()
        logger.info("[WORKER] draining")

    if args.health or args.watch:
        deadline = time.monotonic() + max(0.0, args.watch)
        while True:
            print(json.dumps(pool.snapshot(), indent=2))
            if args.watch <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(min(5.0, args.watch or 5.0))
        return 0

    logger.info(
        "[WORKER] pool ready concurrency=%s workers=%s",
        pool.concurrency,
        len(get_worker_registry().list_workers()),
    )
    logger.info("Workers run inside the API process via POST /analyze-apk enqueue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
