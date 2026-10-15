"""Phase 12C — Verifier (deterministic post-action assessment).

Compares before/after Observation (+ executor success). Does not call LLM/OCR/VLM.
Does not execute UI or mutate NavigationGraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.executor import ExecutorResult
from app.modules.exploration.log_tags import log_verifier
from app.modules.exploration.observation import Observation


class VerifyOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    STATE_CHANGED = "STATE_CHANGED"
    NO_CHANGE = "NO_CHANGE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass
class VerifyResult:
    outcome: VerifyOutcome
    before_state_id: str | None = None
    after_state_id: str | None = None
    activity_changed: bool = False
    ui_changed: bool = False
    hitl_appeared: bool = False
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome in (
            VerifyOutcome.SUCCESS,
            VerifyOutcome.STATE_CHANGED,
            VerifyOutcome.NO_CHANGE,  # wait / intentional settle can be valid
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "before_state_id": self.before_state_id,
            "after_state_id": self.after_state_id,
            "activity_changed": self.activity_changed,
            "ui_changed": self.ui_changed,
            "hitl_appeared": self.hitl_appeared,
            "reason": self.reason,
            "ok": self.ok,
            "meta": dict(self.meta),
        }


class ActionVerifier:
    """Deterministic verification using Observation signals."""

    def verify(
        self,
        *,
        planned: PlannedAction | None,
        executor_result: ExecutorResult | None,
        before: Observation | None,
        after: Observation | None,
    ) -> VerifyResult:
        before_sid = before.state_id if before else (
            executor_result.before_state_id if executor_result else None
        )
        after_sid = after.state_id if after else None

        if executor_result is not None and executor_result.rejected:
            result = VerifyResult(
                outcome=VerifyOutcome.FAILED,
                before_state_id=before_sid,
                after_state_id=after_sid,
                reason=executor_result.error or "rejected",
            )
            log_verifier("result=%s reason=%s", result.outcome.value, result.reason)
            return result

        if executor_result is not None and not executor_result.success:
            result = VerifyResult(
                outcome=VerifyOutcome.FAILED,
                before_state_id=before_sid,
                after_state_id=after_sid,
                reason=executor_result.error or "executor_failed",
            )
            log_verifier("result=%s reason=%s", result.outcome.value, result.reason)
            return result

        if after is None:
            result = VerifyResult(
                outcome=VerifyOutcome.UNKNOWN,
                before_state_id=before_sid,
                reason="missing_after_observation",
            )
            log_verifier("result=%s", result.outcome.value)
            return result

        hitl = bool(after.hitl_required)
        activity_changed = False
        if before is not None and before.activity and after.activity:
            activity_changed = before.activity != after.activity

        state_changed = bool(
            before_sid and after_sid and before_sid != after_sid
        )
        ui_changed = self._ui_changed(before, after)

        kind = (planned.kind if planned else "") or ""

        if hitl:
            result = VerifyResult(
                outcome=VerifyOutcome.BLOCKED,
                before_state_id=before_sid,
                after_state_id=after_sid,
                activity_changed=activity_changed,
                ui_changed=ui_changed,
                hitl_appeared=True,
                reason="hitl_required",
            )
            log_verifier(
                "result=%s before=%s after=%s",
                result.outcome.value,
                before_sid or "-",
                after_sid or "-",
            )
            return result

        if state_changed or activity_changed:
            result = VerifyResult(
                outcome=VerifyOutcome.STATE_CHANGED,
                before_state_id=before_sid,
                after_state_id=after_sid,
                activity_changed=activity_changed,
                ui_changed=ui_changed,
                reason="state_or_activity_changed",
            )
            log_verifier(
                "result=%s before=%s after=%s",
                result.outcome.value,
                before_sid or "-",
                after_sid or "-",
            )
            return result

        # wait (and similar) may intentionally leave the same state.
        if kind == "wait":
            result = VerifyResult(
                outcome=VerifyOutcome.SUCCESS,
                before_state_id=before_sid,
                after_state_id=after_sid,
                ui_changed=ui_changed,
                reason="wait_completed",
            )
            log_verifier("result=%s action=wait", result.outcome.value)
            return result

        if ui_changed:
            # UI hierarchy changed without a new state_id — not automatic failure.
            result = VerifyResult(
                outcome=VerifyOutcome.SUCCESS,
                before_state_id=before_sid,
                after_state_id=after_sid,
                ui_changed=True,
                reason="ui_changed_same_state",
            )
            log_verifier("result=%s reason=%s", result.outcome.value, result.reason)
            return result

        # Phase 12H — delayed runtime ads may appear without a new state_id.
        if self._ads_appeared(before, after):
            result = VerifyResult(
                outcome=VerifyOutcome.SUCCESS,
                before_state_id=before_sid,
                after_state_id=after_sid,
                ui_changed=False,
                reason="runtime_ads_appeared",
                meta={"ads_after": len(after.detected_ads or [])},
            )
            log_verifier("result=%s reason=%s", result.outcome.value, result.reason)
            return result

        if before is None:
            result = VerifyResult(
                outcome=VerifyOutcome.SUCCESS,
                before_state_id=before_sid,
                after_state_id=after_sid,
                reason="executed_no_before_baseline",
            )
            log_verifier("result=%s", result.outcome.value)
            return result

        result = VerifyResult(
            outcome=VerifyOutcome.NO_CHANGE,
            before_state_id=before_sid,
            after_state_id=after_sid,
            reason="no_state_or_ui_change",
        )
        log_verifier(
            "result=%s before=%s after=%s",
            result.outcome.value,
            before_sid or "-",
            after_sid or "-",
        )
        return result

    def _ui_changed(self, before: Observation | None, after: Observation | None) -> bool:
        if before is None or after is None:
            return False
        if len(before.clickable_elements) != len(after.clickable_elements):
            return True
        if len(before.ui_elements) != len(after.ui_elements):
            return True
        # Compact text signature — avoid logging raw sensitive content.
        before_sig = tuple(sorted((before.visible_text or [])[:30]))
        after_sig = tuple(sorted((after.visible_text or [])[:30]))
        if before_sig != after_sig:
            return True
        if bool(before.webview_detected) != bool(after.webview_detected):
            return True
        return False

    def _ads_appeared(self, before: Observation | None, after: Observation | None) -> bool:
        """True when runtime ads newly appear (never from static intelligence)."""
        if after is None:
            return False
        after_ads = [
            a for a in (after.detected_ads or [])
            if isinstance(a, dict) and a.get("detected")
        ]
        if not after_ads:
            return False
        if before is None:
            return True
        before_ads = [
            a for a in (before.detected_ads or [])
            if isinstance(a, dict) and a.get("detected")
        ]
        if len(after_ads) > len(before_ads):
            return True
        before_keys = {
            (
                str(a.get("type") or ""),
                str(a.get("position") or ""),
                str(a.get("uniqueness_key") or a.get("image_path") or ""),
            )
            for a in before_ads
        }
        for a in after_ads:
            key = (
                str(a.get("type") or ""),
                str(a.get("position") or ""),
                str(a.get("uniqueness_key") or a.get("image_path") or ""),
            )
            if key not in before_keys:
                return True
        return False
