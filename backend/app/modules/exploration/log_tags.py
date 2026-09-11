"""Structured log prefixes for the exploration engine.

Every explorer log line is tagged so a run can be filtered as::

    [EXPLORER] [STATE] [ACTION] [NAVIGATION] [SCREENSHOT]
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.modules.exploration.explorer")


def log_explorer(message: str, *args: object) -> None:
    logger.info("[EXPLORER] " + message, *args)


def log_state(message: str, *args: object) -> None:
    logger.info("[STATE] " + message, *args)


def log_action(message: str, *args: object) -> None:
    logger.info("[ACTION] " + message, *args)


def log_navigation(message: str, *args: object) -> None:
    logger.info("[NAVIGATION] " + message, *args)


def log_screenshot(message: str, *args: object) -> None:
    logger.info("[SCREENSHOT] " + message, *args)
