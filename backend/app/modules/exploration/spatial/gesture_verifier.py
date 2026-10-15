"""Phase 12J — Post-gesture verification (new content / boundary / no-change)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.modules.exploration.log_tags import log_gesture
from app.modules.exploration.observation import Observation
from app.modules.exploration.verifier import VerifyOutcome, VerifyResult


class GestureVerifyOutcome(str, Enum):
    SUCCESS = "SUCCESS"  # new content
    NO_CHANGE = "NO_CHANGE"
    BOUNDARY = "BOUNDARY"
    UNKNOWN = "UNKNOWN"


@dataclass
class GestureVerifyResult:
    outcome: GestureVerifyOutcome
    region_id: str | None = None
    direction: str | None = None
    reason: str = ""
    new_content: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "region_id": self.region_id,
            "direction": self.direction,
            "reason": self.reason,
            "new_content": self.new_content,
            "meta": dict(self.meta),
        }


def _text_set(obs: Observation | None) -> set[str]:
    if obs is None:
        return set()
    return {t.strip().lower() for t in (obs.visible_text or []) if t and t.strip()}


def _clickable_keys(obs: Observation | None) -> set[str]:
    if obs is None:
        return set()
    keys: set[str] = set()
    for el in obs.clickable_elements or []:
        if not isinstance(el, dict):
            continue
        keys.add(
            f"{el.get('resource_id') or ''}|"
            f"{(el.get('text') or el.get('content_description') or '')[:40]}|"
            f"{el.get('bounds')}"
        )
    return keys


def verify_gesture(
    *,
    before: Observation | None,
    after: Observation | None,
    verify: VerifyResult | None = None,
    region_id: str | None = None,
    direction: str | None = None,
    prior_no_change: int = 0,
    no_change_limit: int = 2,
) -> GestureVerifyResult:
    """Classify gesture effect using Observation + optional ActionVerifier result."""
    if after is None:
        result = GestureVerifyResult(
            outcome=GestureVerifyOutcome.UNKNOWN,
            region_id=region_id,
            direction=direction,
            reason="missing_after_observation",
        )
        log_gesture(
            "result=%s region=%s direction=%s",
            result.outcome.value,
            region_id or "-",
            direction or "-",
        )
        return result

    # Prefer existing verifier signals when present.
    if verify is not None:
        if verify.outcome in (VerifyOutcome.STATE_CHANGED,):
            result = GestureVerifyResult(
                outcome=GestureVerifyOutcome.SUCCESS,
                region_id=region_id,
                direction=direction,
                reason="state_changed",
                new_content=True,
            )
            log_gesture(
                "result=new_content state=%s region=%s",
                after.state_id or "-",
                region_id or "-",
            )
            return result
        if verify.outcome == VerifyOutcome.SUCCESS and (
            verify.ui_changed or verify.reason in {"runtime_ads_appeared", "ui_changed_same_state"}
        ):
            result = GestureVerifyResult(
                outcome=GestureVerifyOutcome.SUCCESS,
                region_id=region_id,
                direction=direction,
                reason=verify.reason or "verify_success",
                new_content=True,
            )
            log_gesture(
                "result=new_content region=%s direction=%s reason=%s",
                region_id or "-",
                direction or "-",
                result.reason,
            )
            return result

    before_sid = before.state_id if before else None
    after_sid = after.state_id
    if before_sid and after_sid and before_sid != after_sid:
        result = GestureVerifyResult(
            outcome=GestureVerifyOutcome.SUCCESS,
            region_id=region_id,
            direction=direction,
            reason="new_state_id",
            new_content=True,
        )
        log_gesture("result=new_content state=%s", after_sid)
        return result

    texts_before = _text_set(before)
    texts_after = _text_set(after)
    clicks_before = _clickable_keys(before)
    clicks_after = _clickable_keys(after)
    new_texts = texts_after - texts_before
    new_clicks = clicks_after - clicks_before
    ads_before = len(before.detected_ads) if before else 0
    ads_after = len(after.detected_ads or [])
    if new_texts or new_clicks or ads_after > ads_before:
        result = GestureVerifyResult(
            outcome=GestureVerifyOutcome.SUCCESS,
            region_id=region_id,
            direction=direction,
            reason="new_visible_content",
            new_content=True,
            meta={
                "new_texts": len(new_texts),
                "new_clicks": len(new_clicks),
                "ads_delta": ads_after - ads_before,
            },
        )
        log_gesture(
            "result=new_content region=%s direction=%s texts=%s clicks=%s",
            region_id or "-",
            direction or "-",
            len(new_texts),
            len(new_clicks),
        )
        return result

    # Same content — boundary if we already saw no-change, else NO_CHANGE.
    if prior_no_change + 1 >= no_change_limit:
        result = GestureVerifyResult(
            outcome=GestureVerifyOutcome.BOUNDARY,
            region_id=region_id,
            direction=direction,
            reason="repeated_no_change_boundary",
            new_content=False,
        )
        log_gesture(
            "boundary detected region=%s direction=%s",
            region_id or "-",
            direction or "-",
        )
        return result

    result = GestureVerifyResult(
        outcome=GestureVerifyOutcome.NO_CHANGE,
        region_id=region_id,
        direction=direction,
        reason="same_visible_content",
        new_content=False,
    )
    log_gesture(
        "no_change region=%s direction=%s",
        region_id or "-",
        direction or "-",
    )
    return result
