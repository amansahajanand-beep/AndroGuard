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


def log_observation(message: str, *args: object) -> None:
    logger.info("[OBSERVATION] " + message, *args)


def log_agent_state(message: str, *args: object) -> None:
    logger.info("[AGENT_STATE] " + message, *args)


def log_planner(message: str, *args: object) -> None:
    logger.info("[PLANNER] " + message, *args)


def log_executor(message: str, *args: object) -> None:
    logger.info("[EXECUTOR] " + message, *args)


def log_verifier(message: str, *args: object) -> None:
    logger.info("[VERIFIER] " + message, *args)


def log_supervisor(message: str, *args: object) -> None:
    logger.info("[SUPERVISOR] " + message, *args)


def log_reliability(message: str, *args: object) -> None:
    """Phase 12H — failure/recovery/stop diagnostics (no secrets)."""
    logger.info("[RELIABILITY] " + message, *args)


def log_gesture(message: str, *args: object) -> None:
    """Phase 12J — spatial / gesture exploration diagnostics."""
    logger.info("[GESTURE] " + message, *args)
