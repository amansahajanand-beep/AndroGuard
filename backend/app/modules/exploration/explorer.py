"""Application exploration engine (Phase 4 + Phase 10 decision layer).

Given a running emulator + APK analysis prior knowledge, walk reachable UI
screens, capture unique visual states, and build a navigation graph.

Deterministic planning remains the default. Phase 10 optionally asks AI to
pick among allow-listed PlannedAction candidates only (never shell/ADB/code).
HITL (Phase 7) always runs before any AI decision.

Loop:

1. Stabilize UI / HITL pause when required
2. Dump hierarchy
3. Screenshot + fingerprint
4. Plan unexplored actions (biased by static JSON)
5. Optionally AI-select among candidates (strict schema)
6. Execute one action
7. Observe whether the state is new
8. Backtrack when the page budget / actions are exhausted
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.modules.exploration.action_planner import (
    PlannedAction,
    back_action,
    count_clickables,
    is_external_browser_or_store,
    is_home_launcher,
    is_splash_like,
    is_system_settings,
    is_transient_escape_package,
    apply_swipe_budget,
    default_home_pitch_visible,
    has_real_app_ui,
    looks_like_default_home_gate,
    plan_actions,
    relaunch_action,
)
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.errors import ExplorationEngineError
from app.modules.exploration.launcher import AppLauncher
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ActionExecutor
from app.modules.exploration.log_tags import (
    log_action,
    log_agent_state,
    log_explorer,
    log_navigation,
    log_screenshot,
    log_state,
)
from app.modules.exploration.navigation_graph import NavigationGraph
from app.modules.exploration.observation import Observation
from app.modules.exploration.observation_builder import build_observation, emit_observation_log
from app.modules.exploration.planner import ExplorationPlanner
from app.modules.exploration.prior_knowledge import (
    ExplorationPrior,
    prior_from_analysis,
    prior_from_package,
)
from app.modules.exploration.journey import (
    JourneyState,
    classify_screen,
    expand_section_goals,
    filter_candidates_for_step,
    is_coverage_complete,
    maybe_skip_stale_onboarding,
    note_step_attempt,
    prefer_coverage_actions,
    record_step_action,
    recover_action_for_stuck_step,
    uncovered_coverage_goals,
)
from app.modules.exploration.screenshot_manager import ScreenshotManager
from app.modules.exploration.state_detector import ScreenStateRecord, StateDecision, StateDetector
from app.modules.exploration.supervisor import (
    ExplorationSupervisor,
    SupervisorContext,
    SupervisorDecisionKind,
)
from app.modules.exploration.ui_controller import UIController
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import ActionVerifier


@dataclass
class ExplorationLimits:
    """Configured stop conditions (unique states, not blind screenshot quotas)."""

    target_states_per_page: int = 5
    max_states_per_page: int = 10
    max_actions: int = 200
    max_time_seconds: int = 300
    max_depth: int = 20
    max_unique_states: int = 25
    action_delay_ms: int = 900
    stabilize_ms: int = 500
    splash_wait_seconds: float = 3.0
    splash_max_wait_seconds: float = 45.0
    splash_max_polls: int = 15

    @classmethod
    def from_settings(cls) -> "ExplorationLimits":
        limits = cls(
            target_states_per_page=settings.exploration_target_states_per_page,
            max_states_per_page=settings.exploration_max_states_per_page,
            max_actions=settings.exploration_max_actions,
            max_time_seconds=settings.exploration_timeout_seconds,
            max_depth=settings.exploration_max_depth,
            max_unique_states=settings.exploration_max_states,
            action_delay_ms=settings.exploration_action_delay_ms,
            stabilize_ms=settings.exploration_stabilize_ms,
            splash_wait_seconds=settings.exploration_splash_wait_seconds,
            splash_max_wait_seconds=settings.exploration_splash_max_wait_seconds,
            splash_max_polls=settings.exploration_splash_max_polls,
        )
        if getattr(settings, "exploration_full_coverage_enabled", False):
            # Raise soft floors so we can finish the section checklist.
            limits.max_unique_states = max(
                limits.max_unique_states,
                int(getattr(settings, "exploration_full_coverage_min_states", 50) or 50),
            )
            limits.max_actions = max(
                limits.max_actions,
                int(getattr(settings, "exploration_full_coverage_min_actions", 400) or 400),
            )
            limits.max_time_seconds = max(
                limits.max_time_seconds,
                int(
                    getattr(settings, "exploration_full_coverage_min_timeout_seconds", 600)
                    or 600
                ),
            )
            floor_page = int(
                getattr(settings, "exploration_full_coverage_min_states_per_page", 12) or 12
            )
            limits.target_states_per_page = max(limits.target_states_per_page, floor_page)
            limits.max_states_per_page = max(limits.max_states_per_page, floor_page + 4)
            limits.max_depth = max(limits.max_depth, 30)
        return limits


@dataclass
class ExplorationSession:
    """Result of one explorer run (internal; not the final public API contract)."""

    status: str = "completed"
    stop_reason: str = ""
    package_name: str | None = None
    launch_activity: str | None = None
    graph: NavigationGraph = field(default_factory=NavigationGraph)
    detector_states: list[ScreenStateRecord] = field(default_factory=list)
    actions_performed: int = 0
    screenshots_captured: int = 0
    unique_states: int = 0
    duration_ms: int = 0
    hit_state_limit: bool = False
    hit_action_limit: bool = False
    hit_timeout: bool = False
    hit_depth_limit: bool = False
    warnings: list[str] = field(default_factory=list)
    prior: ExplorationPrior | None = None
    activity_trail: list[str] = field(default_factory=list)
    blueprint: dict[str, Any] | None = None
    covered_goal_evidence: dict[str, list[str]] = field(default_factory=dict)
    ad_types_found: list[str] = field(default_factory=list)
    # Phase 12A — unified observation (read-only; does not drive decisions).
    current_observation: Observation | None = None
    observations: list[Observation] = field(default_factory=list)
    # Phase 12B — unified agent memory (read-only orchestration state).
    agent_state: AgentState | None = None
    # Ad dwell: per-screen ad timelines and the extra frames captured for them.
    ad_timelines: dict[str, Any] = field(default_factory=dict)
    ad_frames: list[Any] = field(default_factory=list)
    ad_dwell_spent_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason,
            "package_name": self.package_name,
            "launch_activity": self.launch_activity,
            "actions_performed": self.actions_performed,
            "screenshots_captured": self.screenshots_captured,
            "unique_states": self.unique_states,
            "duration_ms": self.duration_ms,
            "hit_state_limit": self.hit_state_limit,
            "hit_action_limit": self.hit_action_limit,
            "hit_timeout": self.hit_timeout,
            "hit_depth_limit": self.hit_depth_limit,
            "warnings": list(self.warnings),
            "prior": self.prior.to_dict() if self.prior else None,
            "activity_trail": list(self.activity_trail),
            "navigation": self.graph.to_dict(),
            "states": [record.to_dict() for record in self.detector_states],
            "current_observation": (
                self.current_observation.to_dict() if self.current_observation else None
            ),
            "observation_count": len(self.observations),
            "agent_state": self.agent_state.to_dict() if self.agent_state else None,
        }


class ExplorationEngine:
    """DFS-ish explorer with per-page unique-state budgets."""

    def __init__(
        self,
        adb: AndroidADB,
        *,
        prior: ExplorationPrior,
        limits: ExplorationLimits | None = None,
        ui: UIController | None = None,
        screenshots: ScreenshotManager | None = None,
        detector: StateDetector | None = None,
        launcher: AppLauncher | None = None,
        output_dir: str | Path | None = None,
        job_id: str | None = None,
        hitl_manager: Any = None,
        application_intelligence: Any | None = None,
    ) -> None:
        self.adb = adb
        self.prior = prior
        self.limits = limits or ExplorationLimits.from_settings()
        self.ui = ui or UIController(adb, settle_ms=self.limits.stabilize_ms)
        self.job_id = job_id
        self.hitl_manager = hitl_manager
        self.application_intelligence = application_intelligence
        if screenshots is not None:
            self.screenshots = screenshots
        else:
            from app.modules.exploration.screenshot_storage import local_screenshots_dir

            resolved_dir = output_dir or local_screenshots_dir(
                prior.package_name, job_id
            )
            self.screenshots = ScreenshotManager(
                adb,
                output_dir=resolved_dir,
                package_name=prior.package_name,
                job_id=job_id,
                upload_to_s3=True,
            )
        self.detector = detector or StateDetector()
        self.launcher = launcher or AppLauncher(adb)
        self.graph = NavigationGraph()
        self._activity_trail: list[str] = []
        self._splash_wait_attempt = 0
        self._hitl_skips: list[str] = []
        self._hitl_paused_seconds: float = 0.0
        self._stagnation_count = 0
        self._ai_meta: dict[str, Any] = {}
        # Taps that previously opened Chrome / Play — never retry (ad click loops).
        self._banned_action_keys: set[str] = set()
        self._journey = JourneyState(
            max_attempts_per_step=int(
                getattr(settings, "exploration_journey_step_budget", 8) or 8
            )
        )
        if getattr(settings, "exploration_full_coverage_enabled", False):
            self._journey.max_attempts_per_step = max(
                self._journey.max_attempts_per_step,
                int(getattr(settings, "exploration_full_coverage_step_budget", 12) or 12),
            )
        self._full_coverage = bool(
            getattr(settings, "exploration_full_coverage_enabled", False)
        )
        self._last_planned: PlannedAction | None = None
        self._active_session: ExplorationSession | None = None
        # Phase 12C — Planner → Executor → Verifier (wraps existing components).
        self.planner = ExplorationPlanner()
        self.executor = ActionExecutor(self.ui)
        self.verifier = ActionVerifier()
        self.supervisor = ExplorationSupervisor()
        self._last_executor_result = None
        self._last_verify_result = None
        self._last_supervisor_decision = None
        self._goal_evaluator = None
        self._ad_placement_detector = None
        self._lang_tapped: set[str] = set()
        self._vision_calls = 0
        self._swipes_on_state: dict[str, int] = {}
        self._last_new_state_action = 0
        self._ad_escape_streak = 0
        self._ad_escape_cooldown = 0

    def run(self) -> ExplorationSession:
        started = time.perf_counter()
        session = ExplorationSession(
            package_name=self.prior.package_name,
            launch_activity=self.prior.launch_activity,
            prior=self.prior,
            graph=self.graph,
        )
        log_explorer(
            "start package=%s launch=%s limits actions=%s time=%ss depth=%s "
            "target/page=%s max/page=%s max_states=%s full_coverage=%s",
            self.prior.package_name,
            self.prior.launch_activity,
            self.limits.max_actions,
            self.limits.max_time_seconds,
            self.limits.max_depth,
            self.limits.target_states_per_page,
            self.limits.max_states_per_page,
            self.limits.max_unique_states,
            self._full_coverage,
        )
        log_explorer(
            "prior activities=%s preferred_labels=%s",
            len(self.prior.activities),
            self.prior.preferred_labels[:12],
        )

        self._active_session = session
        session.agent_state = AgentState.create_initial(
            package_name=self.prior.package_name,
            navigation_graph=self.graph,
            max_actions=self.limits.max_actions,
            max_states=self.limits.max_unique_states,
            max_depth=self.limits.max_depth,
            job_id=self.job_id,
            application_intelligence=self.application_intelligence,
        )
        # Share region memory with ActionPlanner via prior.
        self.prior.region_memory = session.agent_state.region_memory
        if self.application_intelligence is not None:
            try:
                summary = self.application_intelligence.to_ai_summary()
                log_agent_state(
                    "apk_intelligence attached status=%s ads=%s webview=%s features=%s",
                    summary.get("status"),
                    len(summary.get("ad_sdk_signals") or []),
                    summary.get("webview_present"),
                    len(summary.get("features") or []),
                )
            except Exception:
                pass
            try:
                from app.modules.exploration.ad_goals import seed_ad_goals_from_intelligence

                added = seed_ad_goals_from_intelligence(
                    session.agent_state, self.application_intelligence
                )
                if added:
                    log_agent_state(
                        "ad_goals seeded count=%s targets=%s",
                        len(added),
                        ",".join((g.target_ad_type or "?") for g in added),
                    )
            except Exception as exc:
                log_explorer("ad goal seed skipped (%s)", type(exc).__name__)
        log_agent_state(
            "initialized package=%s max_actions=%s max_states=%s",
            self.prior.package_name,
            self.limits.max_actions,
            self.limits.max_unique_states,
        )
        try:
            self._ensure_foreground()
            # Splash / permission dialogs: poll without burning swipe/menu actions.
            self._await_interactive_ui(session)
            entry = self._observe(
                trigger_action="entry",
                parent_id=None,
                depth=0,
                is_entry_point=True,
                label="entry",
            )
            session.screenshots_captured += 1
            log_state(
                "entry state_id=%s new=%s activity=%s",
                entry.state_id,
                entry.is_new,
                entry.visual.activity,
            )

            session.stop_reason = self._explore_loop(session, started)
            if not session.stop_reason:
                session.stop_reason = "completed"
            if session.stop_reason in {"stopped_by_human", "hitl_timeout"}:
                session.status = "partial"
            else:
                session.status = "completed"
        except ExplorationEngineError:
            raise
        except Exception as exc:
            session.status = "failed"
            session.stop_reason = str(exc)
            session.warnings.append(str(exc))
            log_explorer("failed: %s", exc)
            raise ExplorationEngineError(str(exc)) from exc
        finally:
            session.detector_states = list(self.detector.states)
            session.unique_states = len(self.detector.states)
            session.activity_trail = list(self._activity_trail)
            session.duration_ms = int((time.perf_counter() - started) * 1000)
            session.graph = self.graph
            session.blueprint = dict(self.prior.blueprint) if self.prior.blueprint else None
            session.covered_goal_evidence = {
                k: list(v) for k, v in self.prior.covered_goal_evidence.items()
            }
            if session.agent_state is not None:
                try:
                    session.agent_state.sync_budgets(
                        actions_used=session.actions_performed,
                        states_discovered=session.unique_states,
                        current_depth=self.graph.max_depth(),
                    )
                    if session.status == "failed":
                        session.agent_state.mark_failed(reason=session.stop_reason)
                    else:
                        session.agent_state.mark_completed(reason=session.stop_reason)
                    log_agent_state(
                        "final status=%s actions=%s states=%s history=%s",
                        session.agent_state.status.value,
                        session.agent_state.actions_used,
                        session.agent_state.states_discovered,
                        len(session.agent_state.history),
                    )
                except Exception as exc:
                    log_explorer("agent_state finalize skipped (%s)", type(exc).__name__)
            log_explorer(
                "done status=%s reason=%s unique_states=%s actions=%s duration_ms=%s",
                session.status,
                session.stop_reason,
                session.unique_states,
                session.actions_performed,
                session.duration_ms,
            )
            log_navigation("tree\n%s", self.graph.ascii_tree())
            self._active_session = None

        return session

    # ------------------------------------------------------------------ loop

    def _explore_loop(self, session: ExplorationSession, started: float) -> str:
        self._last_new_state_action = session.actions_performed
        while True:
            reason = self._stop_reason(session, started)
            if reason:
                return reason

            if self._full_coverage and is_coverage_complete(self.prior):
                log_explorer(
                    "full coverage complete — checklist done states=%s actions=%s",
                    len(self.detector.states),
                    session.actions_performed,
                )
                return "coverage_complete"

            # Proactive ad close / skip before HITL.
            self._maybe_dismiss_ads(session)

            # System home: swipe right into the default-home app (do not cold relaunch first).
            if self._on_system_home():
                log_explorer(
                    "explore loop: system home detected — swipe-right into default app"
                )
                session.warnings.append(
                    "On emulator Home; swiped right to open default application."
                )
                entered = self._recover_from_system_home()
                session.actions_performed += 1
                try:
                    decision = self._observe(
                        trigger_action="swipe_right",
                        parent_id=self.graph.current_state_id,
                        depth=self.graph.depth_of(self.graph.current_state_id or "") + 1,
                        is_entry_point=False,
                        label=(
                            "home swipe-right enter default"
                            if entered
                            else "home swipe-right then resume"
                        ),
                    )
                    session.screenshots_captured += 1
                    if decision.state_id:
                        self.graph.set_current(decision.state_id)
                except Exception as exc:
                    log_explorer("post-home swipe enter observe failed: %s", exc)
                continue

            hitl_reason = self._maybe_hitl_pause(session)
            if hitl_reason:
                return hitl_reason

            current_id = self.graph.current_state_id
            if not current_id:
                return "no_current_state"

            depth = self.graph.depth_of(current_id)
            if depth >= self.limits.max_depth:
                session.hit_depth_limit = True
                log_navigation("depth limit at %s — backtracking", depth)
                if not self._backtrack(session):
                    return "max_exploration_depth"
                continue

            child_count = self.graph.unique_child_count(current_id)
            coverage_pending = self._full_coverage and not is_coverage_complete(self.prior)
            # Soft page target: in full-coverage mode keep going until checklist done.
            if (
                child_count >= self.limits.target_states_per_page
                and not coverage_pending
            ):
                log_navigation(
                    "page target reached state=%s unique_children=%s — backtracking",
                    current_id,
                    child_count,
                )
                if not self._backtrack(session):
                    return "target_states_per_page"
                continue

            if child_count >= self.limits.max_states_per_page:
                log_navigation(
                    "page max reached state=%s unique_children=%s — backtracking",
                    current_id,
                    child_count,
                )
                if not self._backtrack(session):
                    return "max_states_per_page"
                continue

            planned = self._next_action(current_id)
            if planned is None:
                log_navigation("no unexplored actions at %s — backtracking", current_id)
                if not self._backtrack(session):
                    if self._full_coverage and not is_coverage_complete(self.prior):
                        remaining = [
                            str(g.get("id")) for g in uncovered_coverage_goals(self.prior)
                        ]
                        log_explorer(
                            "coverage incomplete after exhaustion remaining=%s",
                            ",".join(remaining[:12]),
                        )
                        return "coverage_incomplete"
                    return "no_meaningful_unexplored_actions"
                continue

            if planned.kind == "stop":
                session.warnings.append(
                    f"AI requested stop: {(planned.meta or {}).get('reason') or 'no reason'}"
                )
                log_explorer("AI stop — ending exploration")
                return "ai_stop"

            self._execute_and_observe(session, planned, current_id)
            stop = self._apply_supervisor_decision(session, planned, current_id)
            if stop:
                return stop

    def _vision_guided(self, candidates: list[PlannedAction]) -> tuple[list[PlannedAction], PlannedAction | None]:
        """Let a vision model drop ad candidates and pick what a person would tap.

        Only ever chooses among ``candidates``; any failure leaves them untouched.
        """
        if not getattr(settings, "vision_planner_enabled", False):
            return candidates, None
        if self._vision_calls >= int(settings.vision_planner_max_calls):
            return candidates, None
        taps = [
            item
            for item in candidates
            if item.kind == "tap" and (item.meta or {}).get("bounds")
        ][:12]
        if len(taps) < int(settings.vision_planner_min_candidates):
            return candidates, None
        try:
            from app.modules.ai_explorer.vision_advisor import choose_with_vision

            png = self.adb.screencap_png()
            self._vision_calls += 1
            verdict = choose_with_vision(
                png, [(item.label, item.meta["bounds"]) for item in taps]
            )
        except Exception as exc:
            log_explorer("vision planner skipped (%s)", type(exc).__name__)
            return candidates, None
        if verdict is None:
            return candidates, None

        ad_keys = {taps[i - 1].key for i in verdict.ad_indexes}
        if ad_keys:
            self._banned_action_keys.update(ad_keys)
            candidates = [item for item in candidates if item.key not in ad_keys]
            log_explorer("vision planner marked %s candidate(s) as ads", len(ad_keys))
        if verdict.choice_index is not None:
            picked = taps[verdict.choice_index - 1]
            log_explorer(
                "vision planner chose '%s' (%s): %s",
                picked.label,
                verdict.screen_kind or "screen",
                verdict.reason,
            )
            return candidates, picked
        return candidates, None

    def _escape_ad_if_present(self, session: ExplorationSession) -> bool:
        """Detect an ad (even inside the app's own package) and get back to app content.

        Returns True when an ad was on screen, so the caller skips planning this tick.
        """
        if not getattr(settings, "ad_escape_enabled", True):
            return False
        if self._ad_escape_cooldown > 0:
            self._ad_escape_cooldown -= 1
            return False
        from app.modules.ai_explorer.assist import plan_ad_dismiss_actions
        from app.modules.exploration.ad_escape import escape_ad, is_ad_screen

        try:
            elements, screen_size, activity = self._dump_full()
            package = self.launcher.current_package()
            if not is_ad_screen(
                elements,
                activity=activity,
                package=package,
                target_package=self.prior.package_name,
                screen_size=screen_size,
            ):
                self._ad_escape_streak = 0
                return False
        except Exception as exc:
            log_explorer("ad check skipped (%s)", exc)
            return False

        def recover() -> bool:
            if self._recover_to_target_app(session):
                try:
                    elements, size, act = self._dump_full()
                    still_ad = is_ad_screen(
                        elements,
                        activity=act,
                        package=self.launcher.current_package(),
                        target_package=self.prior.package_name,
                        screen_size=size,
                    )
                except Exception:
                    still_ad = False
                if not still_ad:
                    return True
                # The ad lives in our own task and Back/Close did nothing: restart the app.
                log_explorer("ad still on screen after escape — force-stop and relaunch")
                try:
                    self.launcher.force_stop(self.prior.package_name)
                except Exception as exc:
                    log_explorer("force_stop failed: %s", exc)
            self._relaunch_target(force=True)
            return bool(self.launcher.is_foreground(self.prior.package_name))

        result = escape_ad(
            ui=self.ui,
            dump=self._dump_full,
            package=self.launcher.current_package,
            is_foreground=lambda: bool(self.launcher.is_foreground(self.prior.package_name)),
            target_package=self.prior.package_name,
            dismiss_candidates=plan_ad_dismiss_actions,
            recover=recover,
            settle=self._settle,
        )
        if not result.ad_seen:
            self._ad_escape_streak = 0
            return False
        self._ad_escape_streak += 1
        if self._ad_escape_streak >= 3:
            self._ad_escape_streak = 0
            self._ad_escape_cooldown = 8
            session.warnings.append("Ad escape kept firing on the same screen; pausing it for 8 steps.")
            log_explorer("ad escape standing down for 8 steps (repeated firing)")
        session.actions_performed += max(1, len(result.steps))
        log_explorer("ad escape steps=%s escaped=%s", result.steps, result.escaped)
        session.warnings.append(
            "Ad screen " + ("closed" if result.escaped else "could not be closed") + ": " + ", ".join(result.steps[-6:])
        )
        return True

    def _maybe_dismiss_ads(self, session: ExplorationSession) -> None:
        """Tap Close/Skip on interstitial ads; Back if creative has no close control."""
        if getattr(settings, "ad_escape_enabled", True):
            # The verified escape is the only ad-closing path. The older heuristic below mistook
            # a normal screen with a bottom ad plus a corner icon for a fullscreen ad and pressed
            # Back on the app's real home screen.
            self._escape_ad_if_present(session)
            return
        if not getattr(settings, "ai_assist_gates_enabled", True):
            return
        try:
            from app.modules.ai_explorer.assist import try_dismiss_ads

            elements, screen_size, activity = self._dump_full()
            if activity and any(
                token in activity.lower()
                for token in ("permission", "packageinstaller", "settings")
            ):
                return
            # Try up to 2 dismiss steps (Close, then maybe another overlay).
            for attempt in range(2):
                ok, detail = try_dismiss_ads(
                    ui=self.ui,
                    elements=elements,
                    screen_size=screen_size,
                    activity=activity,
                    settle=self._settle,
                    allow_back=True,
                )
                if not ok:
                    break
                session.actions_performed += 1
                log_explorer("Dismissed ad/control via %s (attempt=%s)", detail, attempt)
                session.warnings.append(f"Auto-dismissed ad/control: {detail}")
                elements, screen_size, activity = self._dump_full()
        except Exception as exc:
            log_explorer("Ad dismiss skipped (%s)", exc)

    def _stop_reason(self, session: ExplorationSession, started: float) -> str | None:
        if self.hitl_manager is not None and getattr(self.hitl_manager, "stopped", False):
            return "stopped_by_human"
        if len(self.detector.states) >= self.limits.max_unique_states:
            session.hit_state_limit = True
            return "target_meaningful_states_found"
        if session.actions_performed >= self.limits.max_actions:
            session.hit_action_limit = True
            return "max_exploration_actions"
        stall = int(getattr(settings, "exploration_stall_actions", 0) or 0)
        if (
            stall > 0
            and len(self.detector.states) >= 3
            and session.actions_performed - self._last_new_state_action >= stall
        ):
            log_explorer("no new screen in %s actions - exploration complete", stall)
            return "exploration_exhausted"
        elapsed = time.perf_counter() - started - self._hitl_paused_seconds
        if elapsed >= self.limits.max_time_seconds:
            session.hit_timeout = True
            return "max_exploration_time"
        return None

    def _maybe_hitl_pause(self, session: ExplorationSession) -> str | None:
        """Pause when a human decision is still required after auto-assist.

        Auto-assist (deterministic + optional LLM) handles permissions, default-app,
        Agree/Continue, forms, and similar gates first. Login / OTP / CAPTCHA stay HITL.
        Continue means the human already acted in the emulator.
        """
        if self.hitl_manager is None or not settings.hitl_enabled:
            return None

        from app.modules.hitl import ExplorationCheckpoint, HumanDecision
        from app.modules.hitl.intervention_types import DetectionResult

        elements, screen_size, activity = self._dump_full()
        package = None
        try:
            package = self.launcher.current_package()
        except Exception:
            package = self.prior.package_name

        detection: DetectionResult = self.hitl_manager.detector.detect(
            elements=elements,
            package=package,
            activity=activity,
        )
        if not detection.required:
            return None

        # Auto-assist for permissions / default / consent / forms before HITL.
        # Works with deterministic taps even when the LLM is disabled.
        if getattr(settings, "ai_assist_gates_enabled", True):
            try:
                from app.modules.ai_explorer.assist import is_ai_assistable, try_ai_assist

                if is_ai_assistable(detection):
                    cleared, notes = try_ai_assist(
                        ui=self.ui,
                        elements=elements,
                        detection=detection,
                        activity=activity,
                        package_name=package or self.prior.package_name,
                        screen_size=screen_size,
                        settle=self._settle,
                        relaunch=lambda: self._recover_from_system_home(),
                    )
                    if cleared:
                        log_explorer("Auto-assist cleared gate notes=%s", notes)
                        session.warnings.append(
                            "Auto-assist handled gate: " + "; ".join(notes[-4:])
                        )
                        session.actions_performed += max(1, len(notes))
                        return None
                    # Never pause humans for HOME/default-launcher gates — swipe into
                    # default workspace (or soft-resume). Do NOT press Back.
                    if detection.type is not None and detection.type.value == "default_app":
                        log_explorer(
                            "DEFAULT_APP assist incomplete — home swipe-right enter notes=%s",
                            notes,
                        )
                        try:
                            self._recover_from_system_home()
                            session.actions_performed += 1
                            self._settle()
                        except Exception:
                            pass
                        session.warnings.append(
                            "Skipped Set-as-default gate via home swipe-right (no HITL)."
                        )
                        return None
                    log_explorer("Auto-assist incomplete — escalating to HITL notes=%s", notes)
                    session.warnings.append(
                        "Auto-assist could not finish; waiting for human: "
                        + "; ".join(notes[-4:])
                    )
            except Exception as exc:
                log_explorer("Auto-assist failed; using HITL (%s)", exc)

        # Capture artifacts for the frontend panel (no auto-tap).
        screenshot_bytes: bytes | None = None
        fingerprint: str | None = None
        try:
            shot = self.screenshots.capture(
                trigger_action="hitl_pause",
                activity=activity,
                package_name=self.prior.package_name,
            )
            session.screenshots_captured += 1
            fingerprint = shot.image_hash
            path = Path(shot.local_path)
            if path.is_file():
                screenshot_bytes = path.read_bytes()
        except Exception as exc:
            log_explorer("HITL screenshot capture failed: %s", exc)
            session.warnings.append(f"HITL screenshot failed: {exc}")
        if not screenshot_bytes:
            # Last-resort direct screencap so the popup still has an image.
            try:
                raw = self.adb.screencap_png()
                if raw and raw.startswith(b"\x89PNG"):
                    screenshot_bytes = raw
            except Exception as exc:
                log_explorer("HITL direct screencap failed: %s", exc)

        ui_dump_xml: str | None = None
        try:
            dump = self.ui.dump_ui(package=None)
            ui_dump_xml = getattr(dump, "xml", None)
        except Exception as exc:
            log_explorer("HITL UI dump failed: %s", exc)

        current_id = self.graph.current_state_id
        checkpoint = ExplorationCheckpoint(
            job_id=self.job_id or "",
            intervention_id="",
            current_state_id=current_id,
            parent_state_id=self.graph.parent_state_id,
            current_activity=activity,
            current_package=package,
            depth=self.graph.depth_of(current_id) if current_id else 0,
            actions_performed=session.actions_performed,
            screenshots_captured=session.screenshots_captured,
            unique_states=len(self.detector.states),
            visited_states=list(self.graph.visited_states.keys()),
            visited_actions={k: sorted(v) for k, v in self.graph.visited_actions.items()},
            navigation_graph=self.graph.to_dict(),
            activity_trail=list(self._activity_trail),
            blocked_fingerprint=fingerprint,
            blocked_visible_text=[
                (el.text or el.content_description or "").strip()
                for el in elements
                if (el.text or el.content_description)
            ][:40],
        )

        log_explorer(
            "HITL required type=%s title=%s activity=%s — pausing (no auto-accept)",
            detection.type.value if detection.type else None,
            detection.title,
            activity,
        )
        try:
            if session.agent_state is not None:
                session.agent_state.set_blocked(
                    detection.type.value if detection.type else detection.title,
                    hitl=detection.to_dict(),
                )
                log_agent_state(
                    "blocked reason=%s",
                    session.agent_state.blocked_reason or "-",
                )
        except Exception:
            pass
        session.warnings.append(
            f"Paused for human intervention: {detection.type.value if detection.type else 'unknown'}"
            f" — {detection.title}"
        )

        pause_started = time.perf_counter()
        _intervention, decision = self.hitl_manager.request_intervention(
            detection,
            package=package,
            activity=activity,
            screenshot_bytes=screenshot_bytes,
            ui_dump_xml=ui_dump_xml,
            checkpoint=checkpoint,
            fingerprint=fingerprint,
        )
        self._hitl_paused_seconds += max(0.0, time.perf_counter() - pause_started)

        if decision is HumanDecision.STOP:
            session.status = "partial"
            try:
                if session.agent_state is not None:
                    session.agent_state.clear_blocked()
            except Exception:
                pass
            return "stopped_by_human"
        if decision is HumanDecision.TIMEOUT:
            session.status = "partial"
            session.hit_timeout = True
            try:
                if session.agent_state is not None:
                    session.agent_state.clear_blocked()
            except Exception:
                pass
            return "hitl_timeout"
        if decision is HumanDecision.SKIP:
            self._hitl_skips.append(
                detection.type.value if detection.type else "unknown"
            )
            session.warnings.append(
                "Human skipped intervention; exploration resumed without treating "
                "consent/permission as completed."
            )
            try:
                if session.agent_state is not None:
                    session.agent_state.clear_blocked()
                    log_agent_state("cleared blocked after hitl skip")
            except Exception:
                pass
            # Soft settle then continue from the same graph position.
            self._settle()
            return None

        # CONTINUE: human already acted — verify the gate is gone.
        try:
            if session.agent_state is not None:
                session.agent_state.clear_blocked()
                log_agent_state("cleared blocked after hitl continue")
        except Exception:
            pass
        self._settle()
        elements2, _size2, activity2 = self._dump_full()
        package2 = None
        try:
            package2 = self.launcher.current_package()
        except Exception:
            package2 = package
        fingerprint2 = None
        try:
            shot2 = self.screenshots.capture(
                trigger_action="hitl_resume",
                activity=activity2,
                package_name=self.prior.package_name,
            )
            session.screenshots_captured += 1
            fingerprint2 = shot2.image_hash
        except Exception:
            fingerprint2 = None

        cleared = self.hitl_manager.verify_cleared(
            elements=elements2,
            package=package2,
            activity=activity2,
            previous=detection,
            previous_fingerprint=fingerprint,
            current_fingerprint=fingerprint2,
        )
        if not cleared:
            session.warnings.append(
                "Human Continue pressed but blocking screen still present."
            )
            # Re-enter wait without advancing automation.
            return self._maybe_hitl_pause(session)

        # Observe the post-human screen as a new/duplicate state without restarting.
        try:
            self._observe(
                trigger_action="hitl_continue",
                parent_id=current_id,
                depth=(self.graph.depth_of(current_id) + 1) if current_id else 0,
                is_entry_point=False,
                label="after_human",
            )
            session.screenshots_captured += 1
        except Exception as exc:
            log_explorer("post-HITL observe failed: %s", exc)
        return None

    def _next_action(self, state_id: str) -> PlannedAction | None:
        elements, screen_size, activity = self._dump_full()

        # If an ad opened Chrome / Play Store, escape back to the target app.
        if self._left_target_app(activity):
            current_pkg = None
            try:
                current_pkg = self.launcher.current_package()
            except Exception:
                current_pkg = None
            if is_home_launcher(
                activity, current_pkg, target_package=self.prior.package_name
            ):
                log_explorer(
                    "left target app onto system home (activity=%s) — home swipe-right",
                    activity,
                )
                return relaunch_action(reason="system_home")
            log_explorer(
                "left target app (activity=%s) — scheduling back to recover",
                activity,
            )
            return back_action()

        # Home launcher: swipe right into default app (relaunch only as fallback).
        if self._on_system_home(activity=activity):
            log_explorer("on home launcher (activity=%s) — home swipe-right", activity)
            return relaunch_action(reason="system_home")

        # App "Set as Default" / home-shell pitch — never grant HOME; dismiss or escape.
        real_app_ui = has_real_app_ui(elements, target_package=self.prior.package_name)
        if default_home_pitch_visible(elements) or (
            (looks_like_default_home_gate(elements, activity=activity) or self._is_app_home_shell(activity))
            and not real_app_ui
        ):
            grant_default = str(getattr(settings, "default_app_policy", "dismiss")).lower() == "grant"
            for el in elements:
                label = (el.text or el.content_description or "").strip().lower()
                if (
                    grant_default
                    and el.clickable
                    and el.enabled
                    and el.visible
                    and re.search(r"(set as default|set default|always|use this app|make default)", label)
                ):
                    from app.modules.exploration.actions import TapAction

                    planned = PlannedAction(
                        key=f"tap:grant-default-home:{el.bounds}",
                        action=TapAction(element=el),
                        kind="tap",
                        priority=200,
                        label=el.text or el.content_description or "Set as default",
                        meta={"tag": "default_home_grant"},
                    )
                    log_explorer("default-home gate - granting (DEFAULT_APP_POLICY=grant)")
                    self._last_planned = planned
                    return planned
                if (
                    not grant_default
                    and el.clickable
                    and el.enabled
                    and el.visible
                    and label == "cancel"
                ):
                    from app.modules.exploration.actions import TapAction

                    planned = PlannedAction(
                        key=f"tap:cancel-default-home:{el.bounds}",
                        action=TapAction(element=el),
                        kind="tap",
                        priority=200,
                        label="Cancel",
                        meta={"is_cancel_dialog": True, "tag": "default_home_cancel"},
                    )
                    log_explorer("default-home gate — tapping Cancel")
                    self._last_planned = planned
                    return planned
            log_explorer(
                "default-home / launcher-shell gate (activity=%s) — swipe-right workspace",
                activity,
            )
            return relaunch_action(reason="escape_home_shell")

        if is_splash_like(elements, activity=activity):
            if self._splash_wait_attempt >= self.limits.splash_max_polls and count_clickables(elements) == 0:
                log_explorer(
                    "splash still idle after %s polls activity=%s",
                    self._splash_wait_attempt,
                    activity,
                )
        # Language selection: pick one (English first), then confirm - never wander onto ads.
        try:
            from app.modules.exploration.onboarding import (
                looks_like_language_screen,
                plan_language_actions,
            )

            if looks_like_language_screen(elements, activity=activity):
                for item in plan_language_actions(
                    elements, screen_size=screen_size, skip_keys=self._lang_tapped
                ):
                    if item.key in self._banned_action_keys:
                        continue
                    self._lang_tapped.add(item.key)
                    log_explorer("language screen - %s %s", (item.meta or {}).get("tag"), item.label)
                    self._last_planned = item
                    return item
        except Exception as exc:
            log_explorer("language screen planning skipped (%s)", exc)

        candidates = plan_actions(
            elements,
            prior=self.prior,
            screen_size=screen_size,
            splash_wait_seconds=self.limits.splash_wait_seconds,
            wait_attempt=self._splash_wait_attempt,
            activity=activity,
            prefer_ad_triggers=bool(self.prior.wants_ad_triggers()),
            region_memory=(
                self._active_session.agent_state.region_memory
                if self._active_session is not None
                and self._active_session.agent_state is not None
                else getattr(self.prior, "region_memory", None)
            ),
        )
        prefer_triggers = bool(self.prior.wants_ad_triggers())
        unexplored = [
            item
            for item in candidates
            if not self.graph.action_seen(state_id, item.key)
            and item.key not in self._banned_action_keys
            and not (item.meta or {}).get("is_ad_cta")
            and (prefer_triggers or not (item.meta or {}).get("ad_trigger"))
        ]
        if not unexplored:
            return None

        # A screen only gets a couple of swipes. Each swipe targets a different region, so its key is
        # never "seen", and a swipe that changes nothing otherwise repeats forever while the real
        # controls (tabs, buttons) are never tapped.
        swipe_budget = int(getattr(settings, "exploration_max_swipes_per_state", 2) or 0)
        unexplored = apply_swipe_budget(
            unexplored, swipes_done=self._swipes_on_state.get(state_id, 0), budget=swipe_budget
        )

        # Human-like journey: discover sections, enforce active map step.
        try:
            added = expand_section_goals(
                self.prior,
                elements,
                screen_size=screen_size,
                journey=self._journey,
                incremental=self._full_coverage,
            )
            if added:
                log_explorer("journey expanded sections: %s", ",".join(added))
                if self._full_coverage:
                    remaining = [
                        str(g.get("id")) for g in uncovered_coverage_goals(self.prior)
                    ]
                    log_explorer(
                        "coverage checklist remaining=%s",
                        ",".join(remaining[:16]) or "-",
                    )
        except Exception as exc:
            log_explorer("section expand failed (%s)", exc)

        role = classify_screen(elements, activity=activity, screen_size=screen_size)
        skipped_onboard = maybe_skip_stale_onboarding(
            self.prior,
            elements=elements,
            role=role,
            activity=activity,
        )
        if skipped_onboard:
            log_explorer("journey skipped onboarding=%s (past main UI)", skipped_onboard)

        skipped = note_step_attempt(self.prior, self._journey)
        if skipped:
            log_explorer("journey skipped goal=%s (step budget)", skipped)
            recover = recover_action_for_stuck_step(role=role, candidates=unexplored)
            if recover is not None:
                return recover

        journey_candidates = filter_candidates_for_step(
            unexplored,
            prior=self.prior,
            elements=elements,
            screen_size=screen_size,
            activity=activity,
            journey=self._journey,
        )
        if journey_candidates:
            unexplored = journey_candidates
            active = self.prior.active_goal()
            log_explorer(
                "journey filter kind=%s role=%s candidates=%s",
                (active or {}).get("kind"),
                role,
                len(unexplored),
            )

        if self._full_coverage:
            unexplored = prefer_coverage_actions(unexplored, prior=self.prior)

        # Stuck on the same visual state → force a swipe before more taps.
        if self._stagnation_count >= 1:
            swipes = [
                c
                for c in unexplored
                if c.kind in {"swipe_up", "swipe_down", "swipe_left", "swipe_right", "swipe"}
            ]
            if swipes:
                # Prefer vertical scroll for content discovery.
                preferred = sorted(
                    swipes,
                    key=lambda c: (
                        0 if c.kind == "swipe_up" else 1 if c.kind == "swipe_down" else 2,
                        -c.priority,
                    ),
                )
                log_explorer(
                    "stagnation=%s preferring swipe=%s",
                    self._stagnation_count,
                    preferred[0].kind,
                )
                self._last_planned = preferred[0]
                return preferred[0]

        unexplored, vision_pick = self._vision_guided(unexplored)
        if vision_pick is not None:
            self._last_planned = vision_pick
            return vision_pick
        if not unexplored:
            return None

        # Phase 10/12E: optional AI decision among deterministic candidates.
        # HITL already ran earlier in the loop — AI must never bypass it.
        # Supervisor recovery is applied after execute/verify, not here.
        agent = self._active_session.agent_state if self._active_session else None
        session = self._active_session
        if settings.ai_explorer_enabled:
            try:
                from app.modules.ai_explorer import run_decision_pipeline
                from app.modules.ai_explorer.context import build_planning_context

                visited = sorted(self.graph.visited_actions.get(state_id, set()))
                planning_ctx = build_planning_context(
                    agent_state=agent,
                    observation=(
                        session.current_observation if session is not None else None
                    ),
                    package_name=self.prior.package_name,
                    activity=activity,
                    last_verification=self._last_verify_result,
                    last_supervisor_decision=self._last_supervisor_decision,
                )
                selected, meta = run_decision_pipeline(
                    unexplored,
                    visited_keys=visited,
                    activity=activity,
                    package_name=self.prior.package_name,
                    stagnation_count=self._stagnation_count,
                    plan_notes=self.prior.plan_summary_for_ai(),
                    planning_context=planning_ctx,
                )
                self._ai_meta = meta
                if agent is not None:
                    agent.record_ai_decision(
                        used=bool(meta.get("ai_used")),
                        meta=meta,
                        planner_source=meta.get("planner_source"),
                    )
                if selected is not None:
                    if meta.get("ai_used"):
                        log_explorer(
                            "AI selected key=%s kind=%s reason=%s",
                            selected.key,
                            selected.kind,
                            (meta.get("ai_reason") or "")[:120],
                        )
                    source = "ai" if meta.get("ai_used") else "deterministic"
                    if meta.get("fallback"):
                        source = "deterministic_fallback"
                    plan = self.planner.wrap_selected(
                        selected,
                        candidate_count=len(unexplored),
                        source=source,
                        reason=(meta.get("ai_reason") or meta.get("policy") or "selected")[
                            :160
                        ],
                    )
                    if plan.planned_action is not None:
                        self._last_planned = plan.planned_action
                        return plan.planned_action
            except Exception as exc:
                log_explorer("AI decision layer failed; using deterministic plan (%s)", exc)
                if agent is not None:
                    try:
                        agent.record_ai_decision(
                            used=False,
                            meta={"fallback": "exception", "ai_error": type(exc).__name__},
                            planner_source="DETERMINISTIC_FALLBACK",
                        )
                    except Exception:
                        pass

        plan = self.planner.select(
            unexplored,
            agent_state=agent,
            source="deterministic",
        )
        if agent is not None and not settings.ai_explorer_enabled:
            try:
                agent.record_ai_decision(
                    used=False,
                    meta={"policy": "ai_disabled"},
                    planner_source="DETERMINISTIC",
                )
            except Exception:
                pass
        if plan.stop or plan.planned_action is None:
            return None
        self._last_planned = plan.planned_action
        return plan.planned_action

    def _on_system_home(self, activity: str | None = None) -> bool:
        """True when the emulator is on the system launcher (not our app)."""
        current_pkg = None
        try:
            current_pkg = self.launcher.current_package()
        except Exception:
            current_pkg = None
        if not isinstance(current_pkg, str):
            current_pkg = None
        if current_pkg == self.prior.package_name:
            return False
        try:
            if self.launcher.is_foreground(self.prior.package_name):
                return False
        except Exception:
            pass
        if activity is None:
            try:
                activity = self.launcher.current_component()
            except Exception:
                activity = None
        if not isinstance(activity, str):
            activity = None
        return is_home_launcher(
            activity, current_pkg, target_package=self.prior.package_name
        )

    def _left_target_app(self, activity: str | None) -> bool:
        current_pkg = None
        try:
            current_pkg = self.launcher.current_package()
        except Exception:
            current_pkg = None

        # Target package's own LauncherHomeActivity is still *in* the app.
        if current_pkg == self.prior.package_name or self.launcher.is_foreground(
            self.prior.package_name
        ):
            return False

        if is_home_launcher(
            activity, current_pkg, target_package=self.prior.package_name
        ):
            return True
        if is_external_browser_or_store(activity, current_pkg):
            return True
        if is_transient_escape_package(current_pkg, activity):
            return True
        # System Settings / default-app picker: stay and try to select our app.
        if is_system_settings(activity, current_pkg):
            return False
        if current_pkg and current_pkg != self.prior.package_name:
            if "permissioncontroller" in current_pkg.lower():
                return False
            return True
        return False

    def _is_gate_activity(self, activity: str | None) -> bool:
        """Blocking setup screens (NOT normal splash — splash should be waited out)."""
        if not activity:
            return False
        lowered = activity.lower()
        return any(
            token in lowered
            for token in (
                "defaultapp",
                "default_app",
                "onboarding",
                "welcome",
                "consent",
                "gdpr",
            )
        )

    def _is_splash_activity(self, activity: str | None) -> bool:
        if not activity:
            return False
        return "splash" in activity.lower()

    def _is_app_home_shell(self, activity: str | None) -> bool:
        """True when the target app is acting as the device Home (custom launcher)."""
        if not activity:
            return False
        lowered = activity.lower()
        return "launcherhome" in lowered or lowered.endswith("launcherhomeactivity")

    def _content_launch_activity(self) -> str | None:
        """Prefer a real content activity over splash / DefaultApp / home-shell."""
        preferred = self.prior.launch_activity
        activities = list(self.prior.activities or [])
        if preferred and preferred not in activities:
            activities.insert(0, preferred)

        def _usable(name: str | None) -> bool:
            if not name:
                return False
            if self._is_gate_activity(name) or self._is_app_home_shell(name):
                return False
            if self._is_splash_activity(name):
                return False
            return True

        for activity in activities:
            if _usable(activity):
                return activity
        if _usable(preferred):
            return preferred
        try:
            resolved = self.launcher.resolve_launch_activity(self.prior.package_name)
            if resolved:
                return resolved
        except Exception:
            pass
        return preferred

    def _ensure_foreground(self) -> None:
        """Cold-start once at session begin. Splash is OK — we wait, not kill."""
        try:
            current = self.launcher.current_component()
        except Exception:
            current = None
        if (
            self.launcher.is_foreground(self.prior.package_name)
            and current
            and not self._is_app_home_shell(current)
        ):
            log_explorer("already in target app (%s) — skip cold relaunch", current)
            return

        outcome = self.launcher.prepare_and_launch(
            self.prior.package_name,
            self.prior.launch_activity,
            prefer_content=True,
            cold_start=True,
        )
        if outcome.activity:
            self.prior.launch_activity = outcome.activity
        for warning in outcome.warnings:
            log_explorer("launch note: %s", warning)
        self._settle()

        try:
            current = self.launcher.current_component()
        except Exception:
            current = None
        # Only recover from *home-shell hijack*, never from normal Splash.
        if current and self._is_app_home_shell(current):
            log_explorer("landed on app home-shell (%s) — clearing HOME + resume", current)
            self.launcher.ensure_system_home(avoid_package=self.prior.package_name)
            outcome = self.launcher.resume_app(
                self.prior.package_name, self.prior.launch_activity
            )
            if outcome.activity:
                self.prior.launch_activity = outcome.activity
            self._settle()

    def _enter_via_home_swipe_right(self, *, max_swipes: int = 2) -> bool:
        """From emulator Home (or app home-shell), swipe right into the default workspace.

        After an app is set as the default Home, sliding right on the system
        launcher opens that app — without ``am start`` / cold relaunch.
        """
        for attempt in range(max(1, int(max_swipes))):
            try:
                if self.launcher.is_foreground(self.prior.package_name):
                    current = None
                    try:
                        current = self.launcher.current_component()
                    except Exception:
                        current = None
                    # Already in real content (not empty LauncherHome shell).
                    if current and not self._is_app_home_shell(current) and not self._is_gate_activity(
                        current
                    ):
                        return True
            except Exception:
                pass

            log_explorer("home swipe-right attempt=%s (enter default app)", attempt + 1)
            try:
                self.ui.swipe_right(duration_ms=400)
            except Exception as exc:
                log_explorer("home swipe-right failed: %s", exc)
                return False
            self._settle()
            try:
                if self.launcher.is_foreground(self.prior.package_name):
                    current = None
                    try:
                        current = self.launcher.current_component()
                    except Exception:
                        current = None
                    log_explorer(
                        "entered target via home swipe-right activity=%s",
                        (current or "-")[-80:],
                    )
                    # Even LauncherHomeActivity of target counts as entered;
                    # one more swipe may open content on a subsequent loop.
                    return True
            except Exception:
                pass
        return False

    def _recover_from_system_home(self, *, force_relaunch_fallback: bool = True) -> bool:
        """Prefer swipe-right into the default app; soft-resume only if needed."""
        if self._enter_via_home_swipe_right():
            return True
        if not force_relaunch_fallback:
            return False
        log_explorer("home swipe-right did not enter app — falling back to soft-resume")
        self._relaunch_target(force=True)
        try:
            return bool(self.launcher.is_foreground(self.prior.package_name))
        except Exception:
            return False

    def _relaunch_target(self, *, force: bool = False) -> None:
        """Soft-resume the app mid-run (no force-stop loop)."""
        if not force and self.launcher.is_foreground(self.prior.package_name):
            current = None
            try:
                current = self.launcher.current_component()
            except Exception:
                current = None
            if current and not self._is_app_home_shell(current):
                return
        # Escape launcher-shell hijack: try swipe-right into workspace first.
        try:
            current = self.launcher.current_component()
        except Exception:
            current = None
        if current and self._is_app_home_shell(current):
            log_explorer("relaunch on HOME shell (%s) — try swipe-right first", current)
            if self._enter_via_home_swipe_right(max_swipes=2):
                try:
                    after = self.launcher.current_component()
                except Exception:
                    after = None
                if after and not self._is_app_home_shell(after) and not self._is_gate_activity(after):
                    return
            log_explorer("relaunch clearing HOME shell (%s)", current)
            try:
                self.launcher.ensure_system_home(avoid_package=self.prior.package_name)
            except Exception as exc:
                log_explorer("ensure_system_home failed: %s", exc)
        # Always prefer a real content activity over Splash / DefaultApp on resume.
        content = self._content_launch_activity()
        if content:
            self.prior.launch_activity = content
        log_explorer(
            "soft-resume %s activity=%s (force=%s)",
            self.prior.package_name,
            (self.prior.launch_activity or "-")[-80:],
            force,
        )
        outcome = self.launcher.resume_app(
            self.prior.package_name, self.prior.launch_activity
        )
        if outcome.activity and not self._is_splash_activity(outcome.activity):
            self.prior.launch_activity = outcome.activity
        self._settle()

    def _recover_to_target_app(
        self,
        session: ExplorationSession,
        *,
        max_backs: int = 6,
        prefer_relaunch: bool = False,
    ) -> bool:
        """Return to the target app.

        Prefer Back for Search/Chrome overlays. Only relaunch from the *system*
        Home screen — never treat the app's own LauncherHomeActivity as Home.
        """
        current_pkg = None
        activity = None
        try:
            activity = self.launcher.current_component()
            current_pkg = self.launcher.current_package()
        except Exception:
            pass

        if current_pkg == self.prior.package_name or self.launcher.is_foreground(
            self.prior.package_name
        ):
            log_explorer("recover: already in target app (activity=%s)", activity)
            return True

        on_system_home = is_home_launcher(
            activity, current_pkg, target_package=self.prior.package_name
        )
        # Transient escapes (Google Search): always try Back first.
        if is_transient_escape_package(current_pkg, activity):
            prefer_relaunch = False

        if prefer_relaunch and on_system_home:
            log_explorer(
                "recover via home swipe-right (system home package=%s activity=%s)",
                current_pkg,
                activity,
            )
            session.warnings.append(
                "Explorer landed on system Home; swiped right to open default application."
            )
            return self._recover_from_system_home()

        for attempt in range(max_backs):
            if self.launcher.is_foreground(self.prior.package_name):
                log_explorer("recovered to target app after back (attempt=%s)", attempt)
                return True
            log_action("recover back attempt=%s (leave overlay/browser)", attempt + 1)
            try:
                self.ui.press_back()
                session.actions_performed += 1
            except Exception as exc:
                log_action("recover back failed: %s", exc)
                break
            time.sleep(max(0.5, self.limits.stabilize_ms / 1000.0))
            try:
                activity = self.launcher.current_component()
                current_pkg = self.launcher.current_package()
            except Exception:
                activity = None
                current_pkg = None
            if self.launcher.is_foreground(self.prior.package_name):
                log_explorer("recovered to target app after back (activity=%s)", activity)
                return True
            if is_home_launcher(
                activity, current_pkg, target_package=self.prior.package_name
            ):
                log_explorer("recover landed on system home — will swipe-right enter")
                break
            # Keep backing out of Search / Chrome / unknown overlays.

        if self.launcher.is_foreground(self.prior.package_name):
            return True

        log_explorer("recover via home swipe-right after leaving to external/home UI")
        session.warnings.append(
            "Explorer left the app; swiped right on Home to open default application."
        )
        return self._recover_from_system_home()

    def _execute_and_observe(
        self,
        session: ExplorationSession,
        planned: PlannedAction,
        from_state_id: str,
    ) -> None:
        if str(planned.kind).startswith("swipe"):
            self._swipes_on_state[from_state_id] = self._swipes_on_state.get(from_state_id, 0) + 1
        # Unique key for back recovery so multiple backs are allowed.
        action_key = planned.key
        if planned.kind == "back":
            action_key = f"back:recover:{session.actions_performed}"
        elif planned.kind == "relaunch":
            action_key = f"relaunch:home:{session.actions_performed}"

        self.graph.mark_action(from_state_id, action_key)

        try:
            record_step_action(self.prior, self._journey)
        except Exception:
            pass

        if planned.kind == "relaunch":
            reason = str((planned.meta or {}).get("reason") or "system_home")
            prefer_swipe = bool((planned.meta or {}).get("prefer_home_swipe", True))
            log_action(
                "execute kind=relaunch key=%s label=%s reason=%s from=%s",
                action_key,
                planned.label,
                reason,
                from_state_id,
            )
            try:
                if prefer_swipe or reason in {"system_home", "escape_home_shell"}:
                    ok = self._recover_from_system_home()
                else:
                    self._relaunch_target(force=True)
                    ok = self.launcher.is_foreground(self.prior.package_name)
            except Exception as exc:
                ok = False
                log_action("home enter/relaunch failed: %s", exc)
                session.warnings.append(f"home enter/relaunch failed: {exc}")
            session.actions_performed += 1
            session.warnings.append(
                "Entered target via home swipe-right (fallback soft-resume if needed)."
            )
            decision = self._observe(
                trigger_action="swipe_right" if prefer_swipe else "relaunch",
                parent_id=from_state_id,
                depth=self.graph.depth_of(from_state_id) + 1,
                is_entry_point=False,
                label=planned.label or "home swipe-right enter",
            )
            session.screenshots_captured += 1
            to_id = decision.state_id
            self.graph.connect(
                from_state_id=from_state_id,
                to_state_id=to_id,
                action_kind="swipe_right" if prefer_swipe else "relaunch",
                action_key=action_key,
                succeeded=ok,
                meta={
                    "label": planned.label,
                    "home_swipe_enter": prefer_swipe,
                    "relaunched": not prefer_swipe,
                    "reason": reason,
                },
            )
            if to_id:
                self.graph.set_current(to_id)
            return

        log_action(
            "execute kind=%s key=%s label=%s from=%s",
            planned.kind,
            action_key,
            planned.label,
            from_state_id,
        )
        before_obs = session.current_observation
        exec_result = self.executor.execute(
            planned,
            agent_state=session.agent_state,
            before_state_id=from_state_id,
            action_key=action_key,
            update_agent_state=True,
        )
        self._last_executor_result = exec_result
        ok = bool(exec_result.success)
        if exec_result.rejected:
            session.warnings.append(
                f"action {planned.kind} rejected: {exec_result.error}"
            )
        elif not ok and exec_result.error:
            log_action("failed kind=%s error=%s", planned.kind, exec_result.error)
            session.warnings.append(f"action {planned.kind} failed: {exec_result.error}")

        session.actions_performed += 1
        try:
            if session.agent_state is not None:
                session.agent_state.sync_budgets(actions_used=session.actions_performed)
        except Exception:
            pass
        if planned.kind == "wait":
            self._splash_wait_attempt += 1
        else:
            self._settle()

        # Map progress: opening drawer/menu covers the sidebar journey step.
        try:
            if ok and (
                planned.kind == "open_menu"
                or bool((planned.meta or {}).get("is_drawer"))
            ):
                newly = self.prior.mark_goal_coverage(
                    activity="open_menu",
                    ui_blob="open_menu navigation drawer sidebar",
                    evidence=f"{planned.kind}:{planned.label or planned.key}",
                )
                if newly:
                    log_explorer("blueprint goals covered via menu: %s", ",".join(newly))
        except Exception:
            pass

        activity = None
        try:
            activity = self.launcher.current_component()
        except Exception:
            activity = None

        left = self._left_target_app(activity)
        onboarding = bool(planned.meta.get("is_onboarding_cta"))
        current_pkg = None
        try:
            current_pkg = self.launcher.current_package()
        except Exception:
            current_pkg = None
        on_system_home = is_home_launcher(
            activity, current_pkg, target_package=self.prior.package_name
        )
        in_settings = is_system_settings(activity)
        escape_chrome = bool(planned.meta.get("is_escape_chrome"))
        # Ban taps that escape into Chrome / Play so we don't re-click the same ad.
        if left and planned.kind == "tap" and not onboarding:
            self._banned_action_keys.add(planned.key)
            log_explorer("Banned action key after leaving app: %s", planned.key)
            session.warnings.append(f"Banned tap that opened external UI: {planned.label or planned.key}")
        if left or (planned.kind == "back" and planned.label == "back"):
            still_out = left or not self.launcher.is_foreground(self.prior.package_name)
            if still_out or on_system_home:
                log_explorer(
                    "action left app (%s) — recovering (relaunch_only_if_system_home=%s)",
                    activity,
                    on_system_home,
                )
                recovered = self._recover_to_target_app(
                    session,
                    prefer_relaunch=on_system_home,
                )
                if recovered:
                    # Back into the same app home — keep exploring; don't force a
                    # fresh "relaunch" observe that burns the run on Splash→Home.
                    if self.launcher.is_foreground(self.prior.package_name) and not on_system_home:
                        decision = self._observe(
                            trigger_action=planned.kind,
                            parent_id=from_state_id,
                            depth=self.graph.depth_of(from_state_id) + 1,
                            is_entry_point=False,
                            label=planned.label or "recover",
                        )
                        session.screenshots_captured += 1
                        to_id = decision.state_id
                        self.graph.connect(
                            from_state_id=from_state_id,
                            to_state_id=to_id,
                            action_kind=planned.kind,
                            action_key=action_key,
                            succeeded=ok,
                            meta={
                                "label": planned.label,
                                "external_ui": activity,
                                "recovered": True,
                                "relaunched": False,
                            },
                        )
                        if decision.is_new:
                            self.graph.set_current(to_id)
                        else:
                            self.graph.set_current(decision.matched_state_id or from_state_id)
                        return
                    decision = self._observe(
                        trigger_action="relaunch",
                        parent_id=from_state_id,
                        depth=self.graph.depth_of(from_state_id) + 1,
                        is_entry_point=False,
                        label="relaunch after system home",
                    )
                    session.screenshots_captured += 1
                    to_id = decision.state_id
                    self.graph.connect(
                        from_state_id=from_state_id,
                        to_state_id=to_id,
                        action_kind=planned.kind,
                        action_key=action_key,
                        succeeded=ok,
                        meta={
                            "label": planned.label,
                            "external_ui": activity,
                            "recovered": True,
                            "relaunched": True,
                        },
                    )
                    self.graph.set_current(to_id)
                    return
                self.graph.connect(
                    from_state_id=from_state_id,
                    to_state_id=from_state_id,
                    action_kind=planned.kind,
                    action_key=action_key,
                    succeeded=False,
                    meta={"label": planned.label, "external_ui": activity, "recovered": False},
                )
                self._stagnation_count += 1
                if from_state_id in self.graph.visited_states:
                    self.graph.set_current(from_state_id)
                return

        # Onboarding CTA while still inside the app (e.g. DefaultApp): observe normally.
        # Do not relaunch — that created Splash→LauncherHome loops.
        if onboarding and not left and not in_settings and not escape_chrome:
            pass

        # After splash waits, skip another screenshot if still identical idle screen.
        if planned.kind == "wait":
            elements, _, activity = self._dump_full()
            if is_splash_like(elements, activity=activity):
                log_state(
                    "splash still idle after wait attempt=%s activity=%s — no extra screenshot",
                    self._splash_wait_attempt,
                    activity,
                )
                self.graph.connect(
                    from_state_id=from_state_id,
                    to_state_id=from_state_id,
                    action_kind=planned.kind,
                    action_key=action_key,
                    succeeded=ok,
                    meta={"label": planned.label, "skipped_screenshot": True},
                )
                self._stagnation_count += 1
                self.graph.set_current(from_state_id)
                self._run_verifier(
                    session,
                    planned=planned,
                    before_obs=before_obs,
                    after_obs=session.current_observation,
                )
                return

        decision = self._observe(
            trigger_action=planned.kind,
            parent_id=from_state_id,
            depth=self.graph.depth_of(from_state_id) + 1,
            is_entry_point=False,
            label=planned.label or planned.kind,
        )
        session.screenshots_captured += 1

        to_id = decision.state_id
        self.graph.connect(
            from_state_id=from_state_id,
            to_state_id=to_id,
            action_kind=planned.kind,
            action_key=action_key,
            succeeded=ok,
            meta={"label": planned.label},
        )

        if decision.is_new:
            self._stagnation_count = 0
            log_state(
                "NEW state_id=%s via %s similarity_to_closest=%.3f",
                to_id,
                planned.kind,
                decision.visual_similarity,
            )
            log_navigation("edge %s -[%s]-> %s (new)", from_state_id, planned.kind, to_id)
            self.graph.set_current(to_id)
        else:
            self._stagnation_count += 1
            log_state(
                "DUPLICATE matched=%s via %s similarity=%.3f",
                decision.matched_state_id,
                planned.kind,
                decision.visual_similarity,
            )
            log_navigation(
                "edge %s -[%s]-> %s (duplicate)",
                from_state_id,
                planned.kind,
                to_id,
            )
            if from_state_id in self.graph.visited_states:
                self.graph.set_current(from_state_id)

        self._run_verifier(
            session,
            planned=planned,
            before_obs=before_obs,
            after_obs=session.current_observation,
        )

    def _run_verifier(
        self,
        session: ExplorationSession,
        *,
        planned: PlannedAction,
        before_obs: Observation | None,
        after_obs: Observation | None,
    ) -> None:
        """Phase 12C verify + Phase 12D supervisor decision (no control-flow here)."""
        try:
            exec_result = self._last_executor_result
            if exec_result is not None and after_obs is not None:
                exec_result.after_state_id = after_obs.state_id
                exec_result.observation_id = after_obs.observation_id
            verify = self.verifier.verify(
                planned=planned,
                executor_result=exec_result,
                before=before_obs,
                after=after_obs,
            )
            self._last_verify_result = verify
            self._record_gesture_coverage(
                session,
                planned=planned,
                before_obs=before_obs,
                after_obs=after_obs,
                verify=verify,
            )
        except Exception as exc:
            log_explorer("verifier skipped (%s)", type(exc).__name__)
            self._last_verify_result = None

        try:
            app_running: bool | None = None
            device_available = True
            try:
                app_running = bool(
                    self.launcher.is_foreground(self.prior.package_name)
                )
            except Exception:
                try:
                    pkg = self.launcher.current_package()
                    app_running = pkg == self.prior.package_name
                except Exception:
                    device_available = False
                    app_running = None

            # System home counts as not running the target app.
            if app_running and self._on_system_home():
                app_running = False

            has_parent = bool(self.graph.parent_state_id)
            decision = self.supervisor.decide(
                SupervisorContext(
                    agent_state=session.agent_state,
                    verify=self._last_verify_result,
                    executor=self._last_executor_result,
                    planned=planned,
                    has_parent=has_parent,
                    app_running=app_running,
                    device_available=device_available,
                    engine_stagnation_count=self._stagnation_count,
                )
            )
            self._last_supervisor_decision = decision
            if (
                self._last_verify_result is not None
                and self._last_verify_result.outcome.value == "STATE_CHANGED"
            ):
                self.supervisor.reset_progress_counters()
        except Exception as exc:
            log_explorer("supervisor skipped (%s)", type(exc).__name__)
            self._last_supervisor_decision = None

    def _record_gesture_coverage(
        self,
        session: ExplorationSession,
        *,
        planned: PlannedAction,
        before_obs: Observation | None,
        after_obs: Observation | None,
        verify: Any,
    ) -> None:
        """Phase 12J — update region memory after a swipe (no extra ADB)."""
        kind = (planned.kind or "").lower()
        if not kind.startswith("swipe"):
            return
        meta = planned.meta or {}
        region_id = meta.get("region_id")
        direction = meta.get("direction") or kind.replace("swipe_", "")
        agent = session.agent_state
        memory = agent.region_memory if agent is not None else None
        if memory is None:
            memory = getattr(self.prior, "region_memory", None)
        if memory is None:
            return
        try:
            from app.core.config import settings as _settings
            from app.modules.exploration.spatial.gesture_verifier import verify_gesture

            no_change_limit = int(
                getattr(_settings, "exploration_gesture_no_change_limit", 2) or 2
            )
            prior_no_change = 0
            if region_id and direction and region_id in getattr(memory, "regions", {}):
                cov = memory.regions[region_id].directions.get(str(direction))
                if cov is not None:
                    prior_no_change = int(cov.no_change_count)

            # Ensure region exists in memory even if only key was planned.
            if region_id and region_id not in memory.regions and meta.get("bounds"):
                from app.modules.exploration.spatial.models import (
                    ExplorationRegion,
                    RegionType,
                    ScrollOrientation,
                )

                bounds = tuple(meta["bounds"])  # type: ignore[arg-type]
                orientation = ScrollOrientation.HORIZONTAL
                if direction in {"up", "down"}:
                    orientation = ScrollOrientation.VERTICAL
                rtype = RegionType.UNKNOWN_SCROLL
                try:
                    rtype = RegionType(str(meta.get("region_type") or "unknown_scroll"))
                except Exception:
                    pass
                memory.merge_region(
                    ExplorationRegion(
                        region_id=str(region_id),
                        region_type=rtype,
                        bounds=bounds,  # type: ignore[arg-type]
                        orientation=orientation,
                        supports_up=direction == "up",
                        supports_down=direction == "down",
                        supports_left=direction == "left",
                        supports_right=direction == "right",
                        confidence=float(meta.get("confidence") or 0.5),
                    )
                )

            gresult = verify_gesture(
                before=before_obs,
                after=after_obs,
                verify=verify,
                region_id=str(region_id) if region_id else None,
                direction=str(direction) if direction else None,
                prior_no_change=prior_no_change,
                no_change_limit=no_change_limit,
            )
            if region_id and direction:
                memory.record_gesture(
                    str(region_id),
                    str(direction),
                    outcome=gresult.outcome.value,
                    state_id=after_obs.state_id if after_obs else None,
                    no_change_limit=no_change_limit,
                )
            if agent is not None:
                agent.bump_reliability("gestures_attempted")
                if gresult.outcome.value == "SUCCESS":
                    agent.bump_reliability("gestures_new_content")
                elif gresult.outcome.value == "NO_CHANGE":
                    agent.bump_reliability("gestures_no_change")
                elif gresult.outcome.value == "BOUNDARY":
                    agent.bump_reliability("gestures_boundary")
        except Exception as exc:
            log_explorer("gesture coverage skipped (%s)", type(exc).__name__)

    def _apply_supervisor_decision(
        self,
        session: ExplorationSession,
        planned: PlannedAction,
        from_state_id: str,
    ) -> str | None:
        """Translate SupervisorDecision into existing engine mechanisms.

        Returns a stop reason string when exploration should end; else None.
        """
        decision = self._last_supervisor_decision
        if decision is None:
            return None

        kind = decision.decision
        if kind is SupervisorDecisionKind.CONTINUE:
            return None

        if kind is SupervisorDecisionKind.RETRY:
            log_explorer(
                "supervisor RETRY action=%s attempt=%s",
                planned.kind,
                decision.retry_count,
            )
            # Re-execute same PlannedAction via Executor (not Supervisor).
            current = self.graph.current_state_id or from_state_id
            self._execute_and_observe(session, planned, current)
            # Nested verify+supervise already ran; apply follow-up once (no deep recursion).
            follow = self._last_supervisor_decision
            if follow is None or follow.decision is SupervisorDecisionKind.CONTINUE:
                return None
            if follow.decision is SupervisorDecisionKind.RETRY:
                # Bound: never nest another retry from here.
                if planned.key:
                    self._banned_action_keys.add(planned.key)
                return None
            if follow.decision is SupervisorDecisionKind.SKIP:
                if planned.key:
                    self._banned_action_keys.add(planned.key)
                return None
            if follow.decision is SupervisorDecisionKind.STOP:
                return follow.reason or "supervisor_stop"
            if follow.decision is SupervisorDecisionKind.BACKTRACK:
                if not self._backtrack(session):
                    return follow.reason or "supervisor_backtrack_exhausted"
                return None
            if follow.decision is SupervisorDecisionKind.RELAUNCH:
                return self._supervisor_relaunch(session)
            if follow.decision is SupervisorDecisionKind.PAUSE_HITL:
                return self._maybe_hitl_pause(session)
            if follow.decision is SupervisorDecisionKind.WAIT:
                self._supervisor_wait()
                return None
            return None

        if kind is SupervisorDecisionKind.WAIT:
            self._supervisor_wait()
            return None

        if kind is SupervisorDecisionKind.SKIP:
            if planned.key:
                self._banned_action_keys.add(planned.key)
            log_explorer("supervisor SKIP key=%s reason=%s", planned.key, decision.reason)
            return None

        if kind is SupervisorDecisionKind.BACKTRACK:
            log_explorer("supervisor BACKTRACK reason=%s", decision.reason)
            if not self._backtrack(session):
                return decision.reason or "supervisor_backtrack_exhausted"
            return None

        if kind is SupervisorDecisionKind.RELAUNCH:
            return self._supervisor_relaunch(session)

        if kind is SupervisorDecisionKind.PAUSE_HITL:
            log_explorer("supervisor PAUSE_HITL reason=%s", decision.reason)
            return self._maybe_hitl_pause(session)

        if kind is SupervisorDecisionKind.STOP:
            log_explorer("supervisor STOP reason=%s", decision.reason)
            return decision.reason or "supervisor_stop"

        return None

    def _supervisor_wait(self) -> None:
        """Bounded settle/wait owned by the engine (not Supervisor)."""
        try:
            # Prefer ad-settle when pursuing an ad goal; otherwise splash wait.
            seconds = float(self.limits.splash_wait_seconds or 1.0)
            try:
                from app.core.config import settings
                from app.modules.exploration.ad_goals import active_ad_goal

                session = self._active_session
                agent = session.agent_state if session else None
                if active_ad_goal(agent) is not None:
                    seconds = float(
                        getattr(settings, "exploration_ad_discovery_settle_seconds", None)
                        or seconds
                    )
            except Exception:
                pass
            seconds = min(1.5, max(0.3, seconds))
            self.ui.wait(seconds=seconds)
        except Exception:
            self._settle()

    def _supervisor_relaunch(self, session: ExplorationSession) -> str | None:
        """Engine-owned recovery requested by Supervisor (home swipe first)."""
        log_explorer("supervisor RELAUNCH (prefer home swipe-right)")
        try:
            if self._on_system_home():
                self._recover_from_system_home()
            else:
                self._relaunch_target(force=True)
            session.actions_performed += 1
            decision = self._observe(
                trigger_action="swipe_right",
                parent_id=self.graph.current_state_id,
                depth=self.graph.depth_of(self.graph.current_state_id or "") + 1,
                is_entry_point=False,
                label="supervisor home enter",
            )
            session.screenshots_captured += 1
            if decision.state_id:
                self.graph.set_current(decision.state_id)
            session.warnings.append(
                "Supervisor recovery: home swipe-right / soft-resume into target app."
            )
        except Exception as exc:
            log_explorer("supervisor relaunch failed: %s", exc)
            return "supervisor_relaunch_failed"
        return None

    def _backtrack(self, session: ExplorationSession) -> bool:
        current_id = self.graph.current_state_id
        parent_id = self.graph.parent_state_id
        if not parent_id or not current_id:
            return False

        planned = back_action()
        log_navigation("backtrack current=%s -> parent=%s", current_id, parent_id)
        log_action("execute kind=back key=back from=%s", current_id)
        try:
            self.ui.press_back()
        except Exception as exc:
            session.warnings.append(f"back failed: {exc}")
            log_action("back failed: %s", exc)
            # Still move the pointer so we do not spin forever.
            self.graph.set_current(parent_id)
            return True

        session.actions_performed += 1
        self.graph.mark_action(current_id, planned.key)
        self._settle()

        decision = self._observe(
            trigger_action="back",
            parent_id=None,
            depth=self.graph.depth_of(parent_id),
            is_entry_point=False,
            label="back",
            # Backtracking should not invent a new tree root casually.
            attach_to_graph_if_new=False,
        )
        session.screenshots_captured += 1
        self.graph.connect(
            from_state_id=current_id,
            to_state_id=decision.state_id,
            action_kind="back",
            action_key=planned.key,
            succeeded=True,
        )

        if decision.matched_state_id and decision.matched_state_id in self.graph.visited_states:
            self.graph.set_current(decision.matched_state_id)
        else:
            self.graph.set_current(parent_id)
        return True

    # --------------------------------------------------------------- observe

    def _observe(
        self,
        *,
        trigger_action: str | None,
        parent_id: str | None,
        depth: int,
        is_entry_point: bool,
        label: str | None,
        attach_to_graph_if_new: bool = True,
    ) -> StateDecision:
        elements, _screen, activity = self._dump_full()
        if activity is None:
            try:
                activity = self.launcher.current_component()
            except Exception:
                activity = None

        shot = self.screenshots.capture(
            trigger_action=trigger_action,
            activity=activity,
            package_name=self.prior.package_name,
        )
        log_screenshot(
            "captured state_id=%s path=%s hash=%s activity=%s trigger=%s",
            shot.state_id,
            shot.local_path,
            shot.image_hash,
            shot.activity,
            trigger_action,
        )

        decision = self.detector.observe(
            shot,
            elements=elements,
            activity=activity,
            trigger_action=trigger_action,
            retain=True,
            label=label,
            depth=depth,
            is_entry_point=is_entry_point,
        )

        if decision.is_new and attach_to_graph_if_new:
            record = next(r for r in self.detector.states if r.state_id == decision.state_id)
            self.graph.add_state(record, parent_id=parent_id, label=label)
        elif decision.matched_state_id and decision.matched_state_id in self.graph.visited_states:
            self.graph.set_current(decision.matched_state_id)

        if activity and (not self._activity_trail or self._activity_trail[-1] != activity):
            self._activity_trail.append(activity)

        # Code-aware coverage: match blueprint goals against activity + visible labels.
        try:
            ui_bits = []
            for el in elements[:80]:
                bit = (el.text or el.content_description or "").strip()
                if bit:
                    ui_bits.append(bit[:40])
            last = self._last_planned
            role = classify_screen(
                elements,
                activity=activity,
                screen_size=None,
            )
            newly = self.prior.mark_goal_coverage(
                activity=activity,
                ui_blob=" ".join(ui_bits),
                evidence=f"{trigger_action or 'observe'}:{activity or '-'}",
                action_kind=(last.kind if last else trigger_action),
                last_label=(last.label if last else None),
                screen_role=role,
            )
            if newly:
                log_explorer("blueprint goals covered: %s", ",".join(newly))
                # After sidebar covered, force section expansion next loop.
                if any(
                    g.get("id") in newly and g.get("kind") == "sidebar"
                    for g in self.prior.goals
                ):
                    self._journey.drawer_opened = True
        except Exception:
            pass

        if count_clickables(elements) > 0:
            self._splash_wait_attempt = 0

        if decision.is_new:
            if self._active_session is not None:
                self._last_new_state_action = self._active_session.actions_performed
            self._dwell_for_ads(decision.state_id, activity)

        # Phase 12A — unified Observation (read-only; never drives decisions).
        try:
            self._record_observation(
                elements=elements,
                screen_size=_screen,
                activity=activity,
                decision=decision,
                screenshot=shot,
                trigger_action=trigger_action,
                parent_id=parent_id,
            )
        except Exception as exc:
            log_explorer("observation build skipped (%s)", type(exc).__name__)

        return decision

    def _dwell_for_ads(self, state_id: str, activity: str | None) -> None:
        """Stay on a new screen briefly and record how its ads appear and move."""
        session = self._active_session
        if session is None or not getattr(settings, "ad_dwell_enabled", True):
            return
        remaining = float(settings.ad_dwell_budget_seconds) - session.ad_dwell_spent_seconds
        if remaining <= 0 or state_id in session.ad_timelines:
            return
        try:
            from app.modules.exploration.ad_discovery import AdPlacementDetector
            from app.modules.exploration.ad_dwell import dwell_observe

            if self._ad_placement_detector is None:
                self._ad_placement_detector = AdPlacementDetector()
            detector = self._ad_placement_detector
            page = None
            if activity:
                page = activity.rsplit(".", 1)[-1].rsplit("/", 1)[-1] or None

            def detect(elements, size, act):
                if not size or size[0] <= 0 or size[1] <= 0:
                    return []
                return detector.detect(
                    elements,
                    screen_width=int(size[0]),
                    screen_height=int(size[1]),
                    page=page or "unknown",
                    trigger_action="ad_dwell",
                    visual_state_id=state_id,
                    activity=act,
                )

            outcome = dwell_observe(
                state_id=state_id,
                page=page,
                activity=activity,
                target_package=self.prior.package_name,
                dump=self._dump_full,
                package=self.launcher.current_package,
                detect=detect,
                capture=lambda: self.screenshots.capture(
                    trigger_action="ad_dwell",
                    activity=activity,
                    package_name=self.prior.package_name,
                ),
                seconds=min(float(settings.ad_dwell_seconds), remaining),
                interval=float(settings.ad_dwell_interval_seconds),
                max_frames=int(settings.ad_dwell_max_frames),
            )
        except Exception as exc:
            log_explorer("ad dwell skipped (%s)", exc)
            return
        session.ad_dwell_spent_seconds += outcome.timeline.dwell_seconds
        session.screenshots_captured += len(outcome.frames)
        session.ad_frames.extend(outcome.frames)
        if outcome.timeline.sightings:
            session.ad_timelines[state_id] = outcome.timeline
            log_explorer(
                "ad dwell state=%s sightings=%s positions=%s stopped=%s",
                state_id,
                len(outcome.timeline.sightings),
                outcome.timeline.positions_seen,
                outcome.timeline.stopped_reason,
            )

    def _record_observation(
        self,
        *,
        elements: list[UIElement],
        screen_size: tuple[int, int],
        activity: str | None,
        decision: StateDecision,
        screenshot: Any,
        trigger_action: str | None,
        parent_id: str | None,
    ) -> None:
        """Build and store Observation without affecting exploration control flow."""
        session = self._active_session
        hitl_result = None
        try:
            from app.modules.hitl.intervention_detector import InterventionDetector

            pkg = None
            try:
                pkg = self.launcher.current_package()
            except Exception:
                pkg = self.prior.package_name
            hitl_result = InterventionDetector(target_package=pkg).detect(
                elements=elements,
                package=pkg,
                activity=activity,
            )
        except Exception:
            hitl_result = None

        meta: dict[str, Any] = {
            "source": "exploration_observe",
            "trigger_action": trigger_action,
            "parent_state_id": parent_id,
            "is_new_state": bool(decision.is_new),
            "visual_similarity": decision.visual_similarity,
            "job_id": self.job_id,
        }
        try:
            ad_fp = decision.ad_placement
            meta["ad_layout_hash"] = getattr(ad_fp, "layout_hash", None)
            meta["ad_slot_count"] = getattr(ad_fp, "slot_count", 0)
        except Exception:
            pass

        # Phase 12G — runtime UI-hierarchy ad detection → Observation.detected_ads.
        # Does not invent ads from static intelligence. Confirmation is runtime-only.
        ad_results = None
        try:
            from app.modules.exploration.ad_discovery import AdPlacementDetector
            from app.modules.exploration.ad_goals import fingerprints_to_ad_results

            if self._ad_placement_detector is None:
                self._ad_placement_detector = AdPlacementDetector()
            w = int(screen_size[0]) if screen_size and screen_size[0] else 0
            h = int(screen_size[1]) if screen_size and len(screen_size) > 1 else 0
            if w > 0 and h > 0:
                shot_path = getattr(screenshot, "local_path", None) if screenshot else None
                page = "unknown"
                if activity:
                    page = activity.rsplit(".", 1)[-1].rsplit("/", 1)[-1] or "unknown"
                fps = self._ad_placement_detector.detect(
                    elements,
                    screen_width=w,
                    screen_height=h,
                    page=page,
                    trigger_action=trigger_action,
                    visual_state_id=decision.state_id,
                    screenshot_path=shot_path,
                    activity=activity,
                )
                ad_results = fingerprints_to_ad_results(fps) or None
        except Exception:
            ad_results = None

        # Phase 6 vision AdDetectionResult may still run later in the pipeline.
        observation = build_observation(
            package_name=self.prior.package_name,
            activity=activity,
            elements=elements,
            screen_size=screen_size if screen_size and screen_size[0] else None,
            state_id=decision.state_id,
            screenshot=screenshot,
            ad_results=ad_results,
            hitl=hitl_result,
            metadata=meta,
        )
        emit_observation_log(observation)
        if session is None:
            return
        session.current_observation = observation
        session.observations.append(observation)
        # Bound memory: keep recent observations only (no image bytes stored).
        max_keep = max(25, int(self.limits.max_unique_states or 25) * 2)
        if len(session.observations) > max_keep:
            del session.observations[: len(session.observations) - max_keep]

        # Phase 12B — update AgentState from Observation (does not drive decisions).
        try:
            agent = session.agent_state
            if agent is not None:
                agent.update_observation(observation)
                agent.sync_budgets(
                    actions_used=session.actions_performed,
                    states_discovered=len(self.graph.visited_states),
                    current_depth=self.graph.depth_of(decision.state_id),
                )
                log_agent_state(
                    "observation updated state=%s activity=%s depth=%s",
                    observation.state_id or "-",
                    (observation.activity or "-")[-60:],
                    agent.current_depth,
                )
                self._evaluate_ad_goals(agent, observation)
        except Exception as exc:
            log_explorer("agent_state observation update skipped (%s)", type(exc).__name__)

    def _evaluate_ad_goals(self, agent: Any, observation: Any) -> None:
        """Deterministic goal evaluation from runtime Observation.detected_ads."""
        try:
            from app.modules.exploration.ad_goals import (
                GoalEvaluator,
                active_ad_goal,
                apply_goal_evaluation,
                _configured_discovery_mode,
            )

            if self._goal_evaluator is None:
                self._goal_evaluator = GoalEvaluator()
            goal = active_ad_goal(agent)
            if goal is None:
                return
            mode = _configured_discovery_mode()
            evaluation = self._goal_evaluator.evaluate(
                goal,
                observation=observation,
                agent_state=agent,
                discovery_mode=mode,
            )
            apply_goal_evaluation(agent, evaluation, discovery_mode=mode)
            if evaluation.outcome == "GOAL_FOUND":
                log_agent_state(
                    "ad_goal FOUND id=%s target=%s discoveries=%s",
                    goal.id,
                    goal.target_ad_type or "ANY",
                    len(agent.discovered_ad_placements),
                )
            elif evaluation.outcome == "GOAL_BLOCKED":
                log_agent_state("ad_goal BLOCKED id=%s reason=%s", goal.id, evaluation.reason)
            elif evaluation.outcome == "GOAL_PROGRESS":
                log_agent_state(
                    "ad_goal PROGRESS id=%s target=%s",
                    goal.id,
                    goal.target_ad_type or "ANY",
                )
        except Exception as exc:
            log_explorer("ad goal evaluation skipped (%s)", type(exc).__name__)

    def _dump_full(self) -> tuple[list[UIElement], tuple[int, int], str | None]:
        """Dump the full window hierarchy (no package filter).

        Filtering to the app package hides system permission dialogs, which
        leaves the explorer staring at a non-interactive splash forever.
        """
        dump = self.ui.dump_ui(package=None)
        try:
            size = self.ui.screen_size()
        except Exception:
            size = (0, 0)
            if dump.elements:
                root = dump.elements[0]
                size = (root.right, root.bottom)
        activity = None
        try:
            activity = self.launcher.current_component()
        except Exception:
            activity = None
        return dump.elements, size, activity

    def _dump(self) -> tuple[list[UIElement], tuple[int, int]]:
        elements, size, _activity = self._dump_full()
        return elements, size

    def _settle(self) -> None:
        delay = max(0, self.limits.action_delay_ms) / 1000.0
        if delay:
            time.sleep(delay)
        extra = max(0, self.limits.stabilize_ms) / 1000.0
        if extra:
            time.sleep(extra)

    def _await_interactive_ui(self, session: ExplorationSession) -> None:
        """Poll until clickables appear or splash timeout — without screenshot spam."""
        deadline = time.perf_counter() + self.limits.splash_max_wait_seconds
        polls = 0
        home_shell_retries = 0
        while time.perf_counter() < deadline and polls < self.limits.splash_max_polls:
            elements, screen_size, activity = self._dump_full()
            clicks = count_clickables(elements)
            log_explorer(
                "preflight UI poll=%s clickables=%s activity=%s",
                polls,
                clicks,
                activity,
            )
            if clicks > 0 and not self._is_app_home_shell(activity):
                log_explorer("interactive UI ready (%s clickables)", clicks)
                self._splash_wait_attempt = 0
                return

            # Dead home-shell: clear HOME role and soft-resume (do NOT cold force-stop loop).
            if self._is_app_home_shell(activity) and home_shell_retries < 2:
                home_shell_retries += 1
                log_explorer(
                    "preflight on app home-shell — clearing HOME + soft resume"
                )
                session.warnings.append(
                    "Target app was the device Home launcher; cleared HOME role and resumed app."
                )
                self.launcher.ensure_system_home(avoid_package=self.prior.package_name)
                self.launcher.resume_app(self.prior.package_name, self.prior.launch_activity)
                self._settle()
                polls += 1
                continue

            # One center tap on first idle poll — some splashes dismiss on tap.
            if polls == 0 and screen_size[0] > 0 and not self._is_app_home_shell(activity):
                try:
                    self.ui.tap_coordinates(screen_size[0] // 2, screen_size[1] // 2)
                    session.actions_performed += 1
                    log_action("preflight center tap on idle/splash screen")
                except Exception as exc:
                    log_action("preflight center tap failed: %s", exc)

            time.sleep(self.limits.splash_wait_seconds)
            polls += 1
            self._splash_wait_attempt = polls
            session.actions_performed += 1  # count soft waits toward budget

        session.warnings.append(
            f"Timed out waiting for interactive UI after {polls} polls "
            f"({self.limits.splash_max_wait_seconds}s); exploring anyway."
        )
        log_explorer("preflight timed out — continuing with current screen")


def run_exploration(
    adb: AndroidADB,
    *,
    analysis: Any = None,
    package_name: str | None = None,
    activity: str | None = None,
    limits: ExplorationLimits | None = None,
    output_dir: str | Path | None = None,
    job_id: str | None = None,
    hitl_manager: Any = None,
) -> ExplorationSession:
    """Entry point used by the CLI and the analysis workflow device stage."""
    prior: ExplorationPrior | None = None
    if analysis is not None:
        prior = prior_from_analysis(analysis)
    if prior is None:
        if not package_name:
            raise ExplorationEngineError(
                "Exploration requires analysis JSON or an explicit --package."
            )
        prior = prior_from_package(package_name, activity=activity)
    elif activity and not prior.launch_activity:
        prior.launch_activity = activity

    application_intelligence = None
    if analysis is not None:
        try:
            from app.modules.apk_intelligence import build_application_intelligence

            application_intelligence = build_application_intelligence(analysis)
        except Exception as exc:
            log_explorer(
                "apk intelligence skipped (%s)",
                type(exc).__name__,
            )

    engine = ExplorationEngine(
        adb,
        prior=prior,
        limits=limits,
        output_dir=output_dir,
        job_id=job_id,
        hitl_manager=hitl_manager,
        application_intelligence=application_intelligence,
    )
    return engine.run()


def session_to_exploration_result(session: ExplorationSession):
    """Map an internal session onto the existing ExplorationResult schema.

    Phase 8 S3 URLs are attached later by ``publish_exploration_screenshots``.
    """
    from app.modules.exploration.blueprint import build_coverage
    from app.schemas.exploration import (
        ExplorationBlueprint,
        ExplorationResult,
        ExplorationScreenshotInfo,
        ExplorationSummary,
        ScreenAdTimeline,
        ScreenState,
        UiAction,
    )

    status = session.status
    if session.status == "failed":
        status = "failed"
    elif session.stop_reason in {"stopped_by_human", "hitl_timeout"}:
        status = "partial"
    elif session.hit_timeout or session.hit_action_limit or session.hit_depth_limit:
        status = "partial" if session.unique_states else "failed"
    elif session.unique_states:
        status = "completed"
    else:
        status = "partial"

    blueprint = None
    if session.blueprint:
        try:
            blueprint = ExplorationBlueprint.model_validate(session.blueprint)
        except Exception:
            blueprint = None
    elif session.prior and session.prior.blueprint:
        try:
            blueprint = ExplorationBlueprint.model_validate(session.prior.blueprint)
        except Exception:
            blueprint = None

    screenshots: list[ExplorationScreenshotInfo] = []
    states: list[ScreenState] = []
    ad_types_found: list[str] = []
    for record in session.detector_states:
        shot = record.screenshot
        info = ExplorationScreenshotInfo(
            file_name=Path(shot.local_path).name,
            state_id=record.state_id,
            width=shot.width,
            height=shot.height,
            format="png",
            byte_size=shot.byte_size,
            sha256=shot.sha256 or None,
            captured_at=shot.timestamp,
            triggering_action=record.trigger_action or shot.trigger_action,
        )
        screenshots.append(info)
        inbound = None
        for edge in session.graph.edges:
            if edge.to_state_id == record.state_id and edge.succeeded and edge.action_kind != "entry":
                inbound = UiAction(
                    kind=edge.action_kind,
                    target_text=(edge.meta or {}).get("label"),
                    from_state_id=edge.from_state_id,
                    to_state_id=edge.to_state_id,
                    succeeded=edge.succeeded,
                )
                break
        extras = {
            "ui_structure_hash": record.visual.ui_structure_hash,
            "ad_placement": record.ad_placement.to_dict(),
        }
        # Heuristic layout fingerprint may already hint at ads.
        try:
            ad_fp = record.ad_placement
            if getattr(ad_fp, "slot_count", 0):
                ad_types_found.append("banner")
        except Exception:
            pass
        states.append(
            ScreenState(
                state_id=record.state_id,
                fingerprint=record.visual.image_hash,
                activity=record.visual.activity,
                label=record.label,
                depth=record.depth,
                is_entry_point=record.is_entry_point,
                element_count=record.visual.element_count,
                clickable_count=record.visual.clickable_count,
                screenshot=info,
                inbound_action=inbound,
                discovered_at=shot.timestamp,
                extras=extras,
            )
        )

    # Extra frames captured while dwelling (ad layout changed) are screenshots too.
    for shot in session.ad_frames:
        screenshots.append(
            ExplorationScreenshotInfo(
                file_name=Path(shot.local_path).name,
                state_id=shot.state_id,
                width=shot.width,
                height=shot.height,
                format="png",
                byte_size=shot.byte_size,
                sha256=shot.sha256 or None,
                captured_at=shot.timestamp,
                triggering_action="ad_dwell",
            )
        )
    ad_timeline = [
        ScreenAdTimeline.model_validate(item.to_dict()) for item in session.ad_timelines.values()
    ]

    coverage = build_coverage(
        blueprint,
        covered_goal_ids=session.covered_goal_evidence
        or (session.prior.covered_goal_evidence if session.prior else None),
        ad_types_found=list(dict.fromkeys(list(session.ad_types_found) + ad_types_found)),
    )

    agent_state_summary = None
    active_goal_payload = None
    ad_discoveries: list[dict] = []
    if session.agent_state is not None:
        try:
            agent_state_summary = session.agent_state.to_dict()
            goal = session.agent_state.active_goal()
            if goal is not None:
                active_goal_payload = goal.to_dict()
            elif session.agent_state.completed_goals:
                # Prefer last completed/found AD_DISCOVERY for reporting.
                for g in reversed(session.agent_state.completed_goals):
                    if g.goal_type == "AD_DISCOVERY":
                        active_goal_payload = g.to_dict()
                        break
            ad_discoveries = [
                d.to_dict() if hasattr(d, "to_dict") else dict(d)
                for d in (session.agent_state.discovered_ad_placements or [])
            ]
        except Exception:
            agent_state_summary = None

    return ExplorationResult(
        status=status,  # type: ignore[arg-type]
        reason=session.stop_reason or None,
        package_name=session.package_name,
        launch_activity=session.launch_activity,
        summary=ExplorationSummary(
            states_discovered=session.unique_states,
            screenshots_captured=session.screenshots_captured,
            actions_performed=session.actions_performed,
            activities_visited=list(session.activity_trail),
            max_depth_reached=session.graph.max_depth(),
            duration_ms=session.duration_ms,
            hit_state_limit=session.hit_state_limit,
            hit_action_limit=session.hit_action_limit,
            hit_timeout=session.hit_timeout,
        ),
        states=states,
        screenshots=screenshots,
        blueprint=blueprint,
        coverage=coverage,
        warnings=list(session.warnings),
        current_observation=(
            session.current_observation.to_dict() if session.current_observation else None
        ),
        observation_count=len(session.observations),
        agent_state=agent_state_summary,
        active_goal=active_goal_payload,
        ad_discoveries=ad_discoveries,
        ad_timeline=ad_timeline,
    )
