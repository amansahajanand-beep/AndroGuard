"""Policy: when to invoke AI vs stay deterministic."""

from __future__ import annotations

from typing import Sequence

from app.modules.exploration.action_planner import PlannedAction


def should_invoke_ai(
    candidates: Sequence[PlannedAction],
    *,
    stagnation_count: int = 0,
    ambiguous_priority_band: int = 15,
    min_candidates: int = 3,
    force: bool = False,
) -> tuple[bool, str]:
    """Return (should_call, reason). Prefer deterministic rules first."""
    if force:
        return True, "forced"
    if not candidates:
        return False, "no_candidates"

    if stagnation_count >= 2:
        return True, "deterministic_crawler_stuck"

    taps = [c for c in candidates if c.kind == "tap"]
    swipes = [c for c in candidates if c.kind.startswith("swipe")]

    if len(taps) >= min_candidates:
        # Ambiguous when top priorities are close.
        top = sorted(taps, key=lambda c: -c.priority)
        if len(top) >= 2 and abs(top[0].priority - top[1].priority) <= ambiguous_priority_band:
            return True, "ambiguous_navigation"
        if len(taps) >= 5:
            return True, "multiple_unexplored_elements"

    if swipes and taps:
        return True, "unexplored_scroll_regions"

    if swipes and stagnation_count >= 1:
        return True, "deeper_scroll_may_reveal_ads"

    return False, "deterministic_sufficient"
