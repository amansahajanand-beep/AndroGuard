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
    plan_actions,
)
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.errors import ExplorationEngineError
from app.modules.exploration.launcher import AppLauncher
from app.modules.exploration.log_tags import (
    log_action,
    log_explorer,
    log_navigation,
    log_screenshot,
    log_state,
)
from app.modules.exploration.navigation_graph import NavigationGraph
from app.modules.exploration.prior_knowledge import (
    ExplorationPrior,
    prior_from_analysis,
    prior_from_package,
)
from app.modules.exploration.screenshot_manager import ScreenshotManager
from app.modules.exploration.state_detector import ScreenStateRecord, StateDecision, StateDetector
from app.modules.exploration.ui_controller import UIController
from app.modules.exploration.ui_element import UIElement


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
        return cls(
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
    ) -> None:
        self.adb = adb
        self.prior = prior
        self.limits = limits or ExplorationLimits.from_settings()
        self.ui = ui or UIController(adb, settle_ms=self.limits.stabilize_ms)
        self.job_id = job_id
        self.hitl_manager = hitl_manager
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
            "target/page=%s max/page=%s max_states=%s",
            self.prior.package_name,
            self.prior.launch_activity,
            self.limits.max_actions,
            self.limits.max_time_seconds,
            self.limits.max_depth,
            self.limits.target_states_per_page,
            self.limits.max_states_per_page,
            self.limits.max_unique_states,
        )
        log_explorer(
            "prior activities=%s preferred_labels=%s",
            len(self.prior.activities),
            self.prior.preferred_labels[:12],
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
            log_explorer(
                "done status=%s reason=%s unique_states=%s actions=%s duration_ms=%s",
                session.status,
                session.stop_reason,
                session.unique_states,
                session.actions_performed,
                session.duration_ms,
            )
            log_navigation("tree\n%s", self.graph.ascii_tree())

        return session

    # ------------------------------------------------------------------ loop

    def _explore_loop(self, session: ExplorationSession, started: float) -> str:
        while True:
            reason = self._stop_reason(session, started)
            if reason:
                return reason

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
            if child_count >= self.limits.target_states_per_page:
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
                    return "no_meaningful_unexplored_actions"
                continue

            if planned.kind == "stop":
                session.warnings.append(
                    f"AI requested stop: {(planned.meta or {}).get('reason') or 'no reason'}"
                )
                log_explorer("AI stop — ending exploration")
                return "ai_stop"

            self._execute_and_observe(session, planned, current_id)

    def _stop_reason(self, session: ExplorationSession, started: float) -> str | None:
        if self.hitl_manager is not None and getattr(self.hitl_manager, "stopped", False):
            return "stopped_by_human"
        if len(self.detector.states) >= self.limits.max_unique_states:
            session.hit_state_limit = True
            return "target_meaningful_states_found"
        if session.actions_performed >= self.limits.max_actions:
            session.hit_action_limit = True
            return "max_exploration_actions"
        elapsed = time.perf_counter() - started - self._hitl_paused_seconds
        if elapsed >= self.limits.max_time_seconds:
            session.hit_timeout = True
            return "max_exploration_time"
        return None

    def _maybe_hitl_pause(self, session: ExplorationSession) -> str | None:
        """Pause exploration when a human decision is required (Phase 7).

        Does **not** auto-accept terms, privacy, permissions, or system prompts.
        Continue means the human already acted in the emulator.
        """
        if self.hitl_manager is None or not settings.hitl_enabled:
            return None

        from app.modules.hitl import ExplorationCheckpoint, HumanDecision
        from app.modules.hitl.intervention_types import DetectionResult

        elements, _size, activity = self._dump_full()
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
            return "stopped_by_human"
        if decision is HumanDecision.TIMEOUT:
            session.status = "partial"
            session.hit_timeout = True
            return "hitl_timeout"
        if decision is HumanDecision.SKIP:
            self._hitl_skips.append(
                detection.type.value if detection.type else "unknown"
            )
            session.warnings.append(
                "Human skipped intervention; exploration resumed without treating "
                "consent/permission as completed."
            )
            # Soft settle then continue from the same graph position.
            self._settle()
            return None

        # CONTINUE: human already acted — verify the gate is gone.
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
            log_explorer(
                "left target app (activity=%s) — scheduling back to recover",
                activity,
            )
            return back_action()

        # Home launcher: Back is useless — force a recover/relaunch action.
        if is_home_launcher(activity, target_package=self.prior.package_name):
            log_explorer("on home launcher (activity=%s) — scheduling back→relaunch path", activity)
            return back_action()

        if is_splash_like(elements, activity=activity):
            if self._splash_wait_attempt >= self.limits.splash_max_polls and count_clickables(elements) == 0:
                log_explorer(
                    "splash still idle after %s polls activity=%s",
                    self._splash_wait_attempt,
                    activity,
                )
        candidates = plan_actions(
            elements,
            prior=self.prior,
            screen_size=screen_size,
            splash_wait_seconds=self.limits.splash_wait_seconds,
            wait_attempt=self._splash_wait_attempt,
            activity=activity,
        )
        unexplored = [
            item for item in candidates if not self.graph.action_seen(state_id, item.key)
        ]
        if not unexplored:
            return None

        # Phase 10: optional AI decision among deterministic candidates.
        # HITL already ran earlier in the loop — AI must never bypass it.
        if settings.ai_explorer_enabled:
            try:
                from app.modules.ai_explorer import run_decision_pipeline

                visited = sorted(self.graph.visited_actions.get(state_id, set()))
                selected, meta = run_decision_pipeline(
                    unexplored,
                    visited_keys=visited,
                    activity=activity,
                    package_name=self.prior.package_name,
                    stagnation_count=self._stagnation_count,
                )
                self._ai_meta = meta
                if selected is not None:
                    if meta.get("ai_used"):
                        log_explorer(
                            "AI selected key=%s kind=%s reason=%s",
                            selected.key,
                            selected.kind,
                            (meta.get("ai_reason") or "")[:120],
                        )
                    return selected
            except Exception as exc:
                log_explorer("AI decision layer failed; using deterministic plan (%s)", exc)

        return unexplored[0]

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
        log_explorer("soft-resume %s (force=%s)", self.prior.package_name, force)
        outcome = self.launcher.resume_app(
            self.prior.package_name, self.prior.launch_activity
        )
        if outcome.activity:
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
                "recover via soft-resume (system home package=%s activity=%s)",
                current_pkg,
                activity,
            )
            session.warnings.append(
                "Explorer landed on system Home; soft-resumed target package (no force-stop)."
            )
            self._relaunch_target(force=True)
            return self.launcher.is_foreground(self.prior.package_name)

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
                log_explorer("recover landed on system home — will relaunch")
                break
            # Keep backing out of Search / Chrome / unknown overlays.

        if self.launcher.is_foreground(self.prior.package_name):
            return True

        log_explorer("relaunching target app after leaving to external/home UI")
        session.warnings.append("Explorer left the app; relaunched target package.")
        self._relaunch_target(force=True)
        return self.launcher.is_foreground(self.prior.package_name)

    def _execute_and_observe(
        self,
        session: ExplorationSession,
        planned: PlannedAction,
        from_state_id: str,
    ) -> None:
        # Unique key for back recovery so multiple backs are allowed.
        action_key = planned.key
        if planned.kind == "back":
            action_key = f"back:recover:{session.actions_performed}"

        self.graph.mark_action(from_state_id, action_key)
        log_action(
            "execute kind=%s key=%s label=%s from=%s",
            planned.kind,
            action_key,
            planned.label,
            from_state_id,
        )
        try:
            result = self.ui.perform(planned.action)
            ok = result.ok
        except Exception as exc:
            ok = False
            log_action("failed kind=%s error=%s", planned.kind, exc)
            session.warnings.append(f"action {planned.kind} failed: {exc}")

        session.actions_performed += 1
        if planned.kind == "wait":
            self._splash_wait_attempt += 1
        else:
            self._settle()

        activity = None
        try:
            activity = self.launcher.current_component()
        except Exception:
            activity = None

        left = self._left_target_app(activity)
        onboarding = bool(planned.meta.get("is_onboarding_cta"))
        on_system_home = is_home_launcher(
            activity, target_package=self.prior.package_name
        )
        in_settings = is_system_settings(activity)
        escape_chrome = bool(planned.meta.get("is_escape_chrome"))
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

        if count_clickables(elements) > 0:
            self._splash_wait_attempt = 0

        return decision

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

    engine = ExplorationEngine(
        adb,
        prior=prior,
        limits=limits,
        output_dir=output_dir,
        job_id=job_id,
        hitl_manager=hitl_manager,
    )
    return engine.run()


def session_to_exploration_result(session: ExplorationSession):
    """Map an internal session onto the existing ExplorationResult schema.

    Phase 8 S3 URLs are attached later by ``publish_exploration_screenshots``.
    """
    from app.schemas.exploration import (
        ExplorationResult,
        ExplorationScreenshotInfo,
        ExplorationSummary,
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

    screenshots: list[ExplorationScreenshotInfo] = []
    states: list[ScreenState] = []
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
                extras={
                    "ui_structure_hash": record.visual.ui_structure_hash,
                    "ad_placement": record.ad_placement.to_dict(),
                },
            )
        )

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
        warnings=list(session.warnings),
    )
