"""Phase 12C — Executor (only component that performs UI actions).

Wraps :class:`UIController.perform`. Rejects non-UI / shell-like actions.
Does not plan, observe, or call the LLM.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import Action, ActionResult
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.log_tags import log_executor

# Approved UI-level action kinds only (matches actions.py + open_menu + swipe_*).
ALLOWED_ACTION_KINDS: frozenset[str] = frozenset(
    {
        "tap",
        "coordinate_tap",
        "swipe",
        "swipe_up",
        "swipe_down",
        "swipe_left",
        "swipe_right",
        "back",
        "home",
        "wait",
        "open_menu",
        "type_text",
    }
)

_FORBIDDEN_KIND_TOKENS = (
    "shell",
    "adb",
    "exec",
    "system",
    "rm",
    "chmod",
    "powershell",
    "python",
    "bash",
    "cmd",
    "am_start",
    "filesystem",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ExecutorResult:
    """Phase 12C execution outcome (wraps low-level :class:`ActionResult`)."""

    action_id: str
    action_kind: str
    action_key: str
    success: bool
    started_at: str
    completed_at: str
    duration_ms: int = 0
    error: str | None = None
    error_type: str | None = None
    before_state_id: str | None = None
    after_state_id: str | None = None
    observation_id: str | None = None
    rejected: bool = False
    ui_result: ActionResult | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "action_key": self.action_key,
            "success": self.success,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_type": self.error_type,
            "before_state_id": self.before_state_id,
            "after_state_id": self.after_state_id,
            "observation_id": self.observation_id,
            "rejected": self.rejected,
            "ui_result": self.ui_result.to_dict() if self.ui_result else None,
            "meta": dict(self.meta),
        }


class ActionExecutor:
    """Execute a validated :class:`PlannedAction` via :class:`UIController`."""

    def __init__(self, ui: Any) -> None:
        self.ui = ui

    def validate(self, planned: PlannedAction) -> str | None:
        """Return an error message if the action is not allowed; else None."""
        kind = (planned.kind or "").strip().lower()
        if not kind:
            return "missing_action_kind"
        if kind == "relaunch":
            # Engine-owned recovery; Executor must not synthesize UI for it.
            return "relaunch_not_executor_owned"
        if kind in _FORBIDDEN_KIND_TOKENS or any(tok in kind for tok in _FORBIDDEN_KIND_TOKENS):
            return f"forbidden_action_kind:{kind}"
        if kind not in ALLOWED_ACTION_KINDS:
            return f"unknown_action_kind:{kind}"
        action = planned.action
        if action is None or not isinstance(action, Action):
            return "missing_action_object"
        # Never allow planner-generated shell strings.
        detail = ""
        try:
            detail = str(getattr(action, "command", "") or "")
        except Exception:
            detail = ""
        lowered = detail.lower()
        if any(
            token in lowered
            for token in ("adb ", "rm ", "chmod ", "powershell", "/bin/", "cmd.exe")
        ):
            return "forbidden_shell_payload"
        return None

    def execute(
        self,
        planned: PlannedAction,
        *,
        agent_state: AgentState | None = None,
        before_state_id: str | None = None,
        action_key: str | None = None,
        update_agent_state: bool = True,
    ) -> ExecutorResult:
        action_id = uuid.uuid4().hex[:12]
        key = action_key or planned.key
        started_at = _utcnow_iso()
        t0 = time.perf_counter()

        reject = self.validate(planned)
        if reject:
            completed_at = _utcnow_iso()
            duration_ms = int((time.perf_counter() - t0) * 1000)
            log_executor(
                "action rejected kind=%s reason=%s",
                planned.kind,
                reject,
            )
            result = ExecutorResult(
                action_id=action_id,
                action_kind=planned.kind,
                action_key=key,
                success=False,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                error=reject,
                error_type="rejected",
                before_state_id=before_state_id,
                rejected=True,
                meta={"label": planned.label},
            )
            if update_agent_state and agent_state is not None:
                agent_state.record_action(
                    action_kind=planned.kind,
                    action_key=key,
                    action_label=planned.label,
                    state_id=before_state_id,
                    success=False,
                    failure_reason=reject,
                )
            return result

        log_executor("action started action=%s key=%s", planned.kind, key[:80])
        ui_result: ActionResult | None = None
        error: str | None = None
        error_type: str | None = None
        success = False
        try:
            ui_result = self.ui.perform(planned.action)
            success = bool(ui_result and ui_result.ok)
            if not success:
                error = (ui_result.detail if ui_result else None) or "perform_not_ok"
                error_type = "ui_failure"
        except Exception as exc:
            success = False
            error = str(exc)[:240]
            error_type = type(exc).__name__

        completed_at = _utcnow_iso()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        if ui_result is not None and ui_result.duration_ms:
            duration_ms = max(duration_ms, int(ui_result.duration_ms))

        log_executor(
            "action completed success=%s action=%s duration_ms=%s",
            success,
            planned.kind,
            duration_ms,
        )

        result = ExecutorResult(
            action_id=action_id,
            action_kind=planned.kind,
            action_key=key,
            success=success,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error=error,
            error_type=error_type,
            before_state_id=before_state_id,
            ui_result=ui_result,
            meta={"label": planned.label},
        )

        if update_agent_state and agent_state is not None:
            if success:
                agent_state.record_action_success(
                    action_kind=planned.kind,
                    action_key=key,
                    action_label=planned.label,
                    state_id=before_state_id,
                )
            else:
                agent_state.record_action(
                    action_kind=planned.kind,
                    action_key=key,
                    action_label=planned.label,
                    state_id=before_state_id,
                    success=False,
                    failure_reason=error or "perform_failed",
                )

        return result
