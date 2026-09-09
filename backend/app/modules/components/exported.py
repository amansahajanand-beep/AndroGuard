from __future__ import annotations


def resolve_exported(
    explicit: bool | None,
    has_intent_filters: bool,
    target_sdk: int | None,
) -> tuple[bool | None, bool, str | None]:
    """Return (exported, inferred, warning)."""
    if explicit is not None:
        return explicit, False, None
    if target_sdk is not None and target_sdk >= 31 and has_intent_filters:
        return (
            None,
            False,
            "android:exported is missing on a component with intent filters and targetSdk >= 31.",
        )
    return has_intent_filters, True, None
