"""Phase 12D — Exploration Supervisor + Recovery (decision only).

Observes Executor/Verifier outcomes and AgentState, then returns a bounded
recovery decision. Does NOT execute UI, ADB, shell, or call an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ExecutorResult
from app.modules.exploration.log_tags import log_supervisor
from app.modules.exploration.verifier import VerifyOutcome, VerifyResult

# Defaults — bounded recovery (not duplicated as global exploration budgets).
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_MAX_NO_CHANGE = 3
_DEFAULT_MAX_RECOVERY_NO_PROGRESS = 3
_DEFAULT_MAX_RELAUNCHES = 2


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SupervisorDecisionKind(str, Enum):
    CONTINUE = "CONTINUE"
    RETRY = "RETRY"
    WAIT = "WAIT"
    BACKTRACK = "BACKTRACK"
    RELAUNCH = "RELAUNCH"
    SKIP = "SKIP"
    PAUSE_HITL = "PAUSE_HITL"
    STOP = "STOP"


@dataclass
class SupervisorDecision:
    decision: SupervisorDecisionKind
    reason: str = ""
    retry_count: int = 0
    action_id: str | None = None
    action_key: str | None = None
    state_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "retry_count": self.retry_count,
            "action_id": self.action_id,
            "action_key": self.action_key,
            "state_id": self.state_id,
            "meta": dict(self.meta),
        }


@dataclass
class SupervisorContext:
    """Evidence snapshot for one post-verify decision."""

    agent_state: AgentState | None = None
    verify: VerifyResult | None = None
    executor: ExecutorResult | None = None
    planned: PlannedAction | None = None
    has_parent: bool = False
    app_running: bool | None = None  # True/False/None(unknown)
    device_available: bool = True
    engine_stagnation_count: int = 0


class ExplorationSupervisor:
    """Deterministic recovery orchestrator (no UI / ADB / LLM)."""

    def __init__(
        self,
        *,
        max_retries_per_action: int = _DEFAULT_MAX_RETRIES,
        max_consecutive_no_change: int = _DEFAULT_MAX_NO_CHANGE,
        max_recovery_without_progress: int = _DEFAULT_MAX_RECOVERY_NO_PROGRESS,
        max_relaunches: int = _DEFAULT_MAX_RELAUNCHES,
    ) -> None:
        self.max_retries_per_action = max(0, int(max_retries_per_action))
        self.max_consecutive_no_change = max(1, int(max_consecutive_no_change))
        self.max_recovery_without_progress = max(1, int(max_recovery_without_progress))
        self.max_relaunches = max(0, int(max_relaunches))

        self._retries: dict[str, int] = {}
        self._waited_keys: set[str] = set()
        self._consecutive_no_change = 0
        self._recovery_without_progress = 0
        self._relaunch_count = 0
        self._last_decision: SupervisorDecision | None = None

    def reset_progress_counters(self) -> None:
        """Call when exploration made forward progress (new state)."""
        self._consecutive_no_change = 0
        self._recovery_without_progress = 0

    def decide(self, ctx: SupervisorContext) -> SupervisorDecision:
        planned = ctx.planned
        verify = ctx.verify
        executor = ctx.executor
        agent = ctx.agent_state

        action_key = (
            (executor.action_key if executor else None)
            or (planned.key if planned else None)
        )
        action_id = executor.action_id if executor else None
        state_id = (
            (verify.after_state_id if verify else None)
            or (agent.current_state_id if agent else None)
        )
        outcome = verify.outcome if verify else None
        kind = (planned.kind if planned else "") or ""

        def emit(
            decision: SupervisorDecisionKind,
            reason: str,
            *,
            retry_count: int = 0,
            meta: dict[str, Any] | None = None,
            counts_as_recovery: bool | None = None,
        ) -> SupervisorDecision:
            nonlocal action_key, action_id, state_id
            result = SupervisorDecision(
                decision=decision,
                reason=reason,
                retry_count=retry_count,
                action_id=action_id,
                action_key=action_key,
                state_id=state_id,
                meta=meta or {},
            )
            if counts_as_recovery is None:
                counts_as_recovery = decision in (
                    SupervisorDecisionKind.RETRY,
                    SupervisorDecisionKind.WAIT,
                    SupervisorDecisionKind.BACKTRACK,
                    SupervisorDecisionKind.RELAUNCH,
                )
            if decision == SupervisorDecisionKind.CONTINUE:
                self.reset_progress_counters()
            elif counts_as_recovery:
                self._recovery_without_progress += 1
            self._last_decision = result
            log_supervisor(
                "outcome=%s action=%s reason=%s decision=%s",
                outcome.value if outcome else "-",
                (kind or action_key or "-")[:40],
                reason[:80],
                decision.value,
            )
            if decision in (
                SupervisorDecisionKind.STOP,
                SupervisorDecisionKind.RELAUNCH,
                SupervisorDecisionKind.BACKTRACK,
                SupervisorDecisionKind.RETRY,
                SupervisorDecisionKind.PAUSE_HITL,
            ):
                try:
                    from app.modules.exploration.log_tags import log_reliability

                    log_reliability(
                        "category=%s action=%s state=%s retry=%s reason=%s",
                        decision.value,
                        (action_key or kind or "-")[:60],
                        (state_id or "-")[:40],
                        retry_count,
                        reason[:80],
                    )
                except Exception:
                    pass
            if agent is not None:
                try:
                    agent.record_recovery(
                        decision=decision.value,
                        reason=reason,
                        action_id=action_id,
                        action_key=action_key,
                        state_id=state_id,
                        attempt=retry_count,
                    )
                except Exception:
                    pass
            return result

        # --- hard stops ---
        if not ctx.device_available:
            return emit(SupervisorDecisionKind.STOP, "device_unavailable")

        if agent is not None:
            if agent.remaining_actions <= 0:
                return emit(SupervisorDecisionKind.STOP, "budget_actions_exhausted")
            if agent.remaining_states <= 0:
                return emit(SupervisorDecisionKind.STOP, "budget_states_exhausted")

        if self._recovery_without_progress >= self.max_recovery_without_progress:
            return emit(
                SupervisorDecisionKind.STOP,
                "recovery_limit_reached",
                meta={"recovery_without_progress": self._recovery_without_progress},
                counts_as_recovery=False,
            )

        # --- HITL highest priority ---
        if outcome == VerifyOutcome.BLOCKED or (
            agent is not None and agent.hitl_required
        ) or (verify is not None and verify.hitl_appeared):
            return emit(SupervisorDecisionKind.PAUSE_HITL, "hitl_required")

        # --- app crash / not running ---
        if ctx.app_running is False:
            if self._relaunch_count >= self.max_relaunches:
                return emit(SupervisorDecisionKind.STOP, "relaunch_limit_reached")
            self._relaunch_count += 1
            return emit(
                SupervisorDecisionKind.RELAUNCH,
                "app_not_running",
                meta={"relaunch_count": self._relaunch_count},
            )

        # --- success paths ---
        if outcome in (VerifyOutcome.SUCCESS, VerifyOutcome.STATE_CHANGED):
            if action_key:
                self._retries.pop(action_key, None)
                self._waited_keys.discard(action_key)
            return emit(
                SupervisorDecisionKind.CONTINUE,
                "ok" if outcome == VerifyOutcome.SUCCESS else "state_changed",
            )

        # --- executor / verify failure ---
        if outcome == VerifyOutcome.FAILED or (
            executor is not None and not executor.success
        ):
            error = ""
            if executor is not None:
                error = (executor.error or executor.error_type or "") or ""
            error_l = error.lower()

            # Non-retryable: rejected / forbidden / unknown kinds
            if executor is not None and executor.rejected:
                return emit(SupervisorDecisionKind.SKIP, error or "rejected")

            if any(
                token in error_l
                for token in (
                    "forbidden",
                    "unknown_action",
                    "missing_action",
                    "not_executor",
                )
            ):
                return emit(SupervisorDecisionKind.SKIP, error or "non_retryable")

            # Device-level hard failure
            if any(
                token in error_l
                for token in ("device offline", "not found", "no devices", "disconnected")
            ):
                return emit(SupervisorDecisionKind.STOP, "device_unavailable")

            retries_used = self._retries.get(action_key or "", 0)
            if action_key and retries_used < self.max_retries_per_action:
                self._retries[action_key] = retries_used + 1
                return emit(
                    SupervisorDecisionKind.RETRY,
                    error or "executor_failed",
                    retry_count=self._retries[action_key],
                )

            # Retry exhausted → skip so Planner can pick another candidate
            return emit(
                SupervisorDecisionKind.SKIP,
                "retry_exhausted",
                retry_count=retries_used,
            )

        # --- no change / unknown / transient ---
        if outcome == VerifyOutcome.NO_CHANGE:
            self._consecutive_no_change += 1
            # wait actions that intentionally stay put are already SUCCESS from verifier;
            # NO_CHANGE on taps/swipes may need wait then escalate.
            if kind == "wait":
                return emit(SupervisorDecisionKind.CONTINUE, "wait_no_change_ok")

            # First NO_CHANGE: short wait once per action key
            if action_key and action_key not in self._waited_keys:
                self._waited_keys.add(action_key)
                return emit(
                    SupervisorDecisionKind.WAIT,
                    "transient_no_change",
                    meta={"consecutive_no_change": self._consecutive_no_change},
                )

            stagnation = max(
                self._consecutive_no_change, int(ctx.engine_stagnation_count or 0)
            )
            if stagnation >= self.max_consecutive_no_change:
                if ctx.has_parent:
                    return emit(
                        SupervisorDecisionKind.BACKTRACK,
                        "stagnation_no_change",
                        meta={"consecutive_no_change": stagnation},
                    )
                return emit(
                    SupervisorDecisionKind.STOP,
                    "stagnation_no_parent",
                    meta={"consecutive_no_change": stagnation},
                )

            # After wait already used, skip this action and let Planner continue
            return emit(
                SupervisorDecisionKind.SKIP,
                "no_change_after_wait",
                meta={"consecutive_no_change": self._consecutive_no_change},
            )

        if outcome == VerifyOutcome.UNKNOWN:
            # Missing observation — wait once, then skip
            if action_key and action_key not in self._waited_keys:
                self._waited_keys.add(action_key)
                return emit(SupervisorDecisionKind.WAIT, "unknown_missing_observation")
            return emit(SupervisorDecisionKind.SKIP, "unknown_after_wait")

        # Fallback
        return emit(SupervisorDecisionKind.CONTINUE, "default_continue")
