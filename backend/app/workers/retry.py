"""Phase 12I — Job-level retry classification (infrastructure vs APK).

Distinct from Phase 12H action/supervisor recovery.
"""

from __future__ import annotations

from typing import Any


# Infrastructure / transient — may retry the whole job on a fresh emulator.
_RETRYABLE_TOKENS = (
    "emulator",
    "boot",
    "adb",
    "device offline",
    "device_unavailable",
    "no devices",
    "disconnected",
    "timeout waiting",
    "not found",
    "connection reset",
    "temporary",
    "unavailable",
    "worker",
)

# APK / deterministic — do not burn retries.
_NON_RETRYABLE_TOKENS = (
    "invalid_file",
    "invalid apk",
    "corrupt",
    "install_failed",
    "installation failed",
    "signature",
    "incompatible",
    "unsupported",
    "parse",
    "manifest",
    "not an apk",
)


def is_retryable_job_failure(
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    exc: BaseException | None = None,
) -> bool:
    """Return True when a fresh job attempt on another/clean emulator may help."""
    blob = " ".join(
        str(x).lower()
        for x in (error_code, error_message, type(exc).__name__ if exc else "", str(exc) if exc else "")
        if x
    )
    if not blob.strip():
        return False
    if any(token in blob for token in _NON_RETRYABLE_TOKENS):
        return False
    if any(token in blob for token in _RETRYABLE_TOKENS):
        return True
    return False


def classify_failure(
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    retryable = is_retryable_job_failure(
        error_code=error_code, error_message=error_message, exc=exc
    )
    return {
        "retryable": retryable,
        "error_code": error_code,
        "error_message": (error_message or str(exc) if exc else None),
        "category": "infrastructure" if retryable else "application",
    }
