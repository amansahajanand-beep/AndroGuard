"""Phase 5 multi-run advertisement placement exploration.

Wraps the Phase 4 exploration engine:

* biases actions toward scroll + ad-trigger taps
* records unique :class:`AdPlacementFingerprint` values per page
* repeats up to ``MAX_EXPLORATION_RUNS`` because ads are probabilistic
* merges and deduplicates across runs
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.exploration.ad_discovery import (
    AdDiscoveryLimits,
    AdPlacementCatalog,
    AdPlacementDetector,
)
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.errors import ExplorationEngineError
from app.modules.exploration.explorer import (
    ExplorationEngine,
    ExplorationLimits,
    ExplorationSession,
)
from app.modules.exploration.launcher import AppLauncher
from app.modules.exploration.log_tags import log_explorer
from app.modules.exploration.prior_knowledge import (
    ExplorationPrior,
    prior_from_analysis,
    prior_from_package,
)

logger = logging.getLogger(__name__)


@dataclass
class AdExplorationCampaign:
    """Merged result of one or more exploration runs focused on ad placements."""

    status: str = "completed"
    stop_reason: str = ""
    package_name: str | None = None
    runs_completed: int = 0
    duration_ms: int = 0
    catalog: AdPlacementCatalog = field(default_factory=AdPlacementCatalog)
    run_sessions: list[ExplorationSession] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def unique_ad_placements(self) -> int:
        return len(self.catalog.placements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason,
            "package_name": self.package_name,
            "runs_completed": self.runs_completed,
            "duration_ms": self.duration_ms,
            "unique_ad_placements": self.unique_ad_placements,
            "ad_placements": self.catalog.to_dict(),
            "warnings": list(self.warnings),
            "runs": [
                {
                    "status": s.status,
                    "stop_reason": s.stop_reason,
                    "unique_states": s.unique_states,
                    "actions_performed": s.actions_performed,
                    "screenshots_captured": s.screenshots_captured,
                    "duration_ms": s.duration_ms,
                }
                for s in self.run_sessions
            ],
        }


class AdAwareExplorationEngine(ExplorationEngine):
    """Phase 4 engine that also fills an :class:`AdPlacementCatalog`."""

    def __init__(
        self,
        adb: AndroidADB,
        *,
        prior: ExplorationPrior,
        limits: ExplorationLimits | None = None,
        ui=None,
        screenshots=None,
        detector=None,
        launcher: AppLauncher | None = None,
        output_dir: str | Path | None = None,
        ad_catalog: AdPlacementCatalog | None = None,
        ad_detector: AdPlacementDetector | None = None,
        run_index: int = 0,
        prefer_ad_triggers: bool = True,
        application_intelligence: Any | None = None,
    ) -> None:
        super().__init__(
            adb,
            prior=prior,
            limits=limits,
            ui=ui,
            screenshots=screenshots,
            detector=detector,
            launcher=launcher,
            output_dir=output_dir,
            application_intelligence=application_intelligence,
        )
        self.ad_catalog = ad_catalog or AdPlacementCatalog()
        self.ad_detector = ad_detector or AdPlacementDetector(
            bbox_quantize=self.ad_catalog.limits.bbox_quantize
        )
        self.run_index = run_index
        self.prefer_ad_triggers = prefer_ad_triggers

    def _next_action(self, state_id: str):  # type: ignore[override]
        from app.modules.exploration.action_planner import (
            back_action,
            count_clickables,
            is_splash_like,
            plan_actions,
        )

        elements, screen_size, activity = self._dump_full()
        if self._left_target_app(activity):
            log_explorer("left target app (activity=%s) — scheduling back to recover", activity)
            return back_action()

        if is_splash_like(elements, activity=activity):
            if (
                self._splash_wait_attempt >= self.limits.splash_max_polls
                and count_clickables(elements) == 0
            ):
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
            prefer_ad_triggers=self.prefer_ad_triggers,
        )
        page = self._page_label(activity)
        target_met = self.ad_catalog.has_reached_target(page)

        def _rank(item) -> tuple:
            if item.meta.get("is_onboarding_cta") or item.meta.get("is_close"):
                tier = 0
            elif target_met and item.kind in {"swipe_down", "swipe_up", "open_menu", "back"}:
                tier = 1
            elif item.meta.get("ad_trigger"):
                tier = 2
            elif item.kind in {"swipe_down", "swipe_up"}:
                tier = 3
            else:
                tier = 4
            return (tier, -item.priority, item.key)

        ordered = sorted(candidates, key=_rank)

        for item in ordered:
            if not self.graph.action_seen(state_id, item.key):
                return item
        return None

    def _observe(self, **kwargs):  # type: ignore[override]
        decision = super()._observe(**kwargs)
        try:
            elements, size, activity = self._dump_full()
            page = self._page_label(activity)
            if self.ad_catalog.has_reached_max(page):
                return decision
            shot_path = None
            for record in self.detector.states:
                if record.state_id == decision.state_id:
                    shot_path = record.screenshot.local_path
                    break
            placements = self.ad_detector.detect(
                elements,
                screen_width=size[0],
                screen_height=size[1],
                page=page,
                trigger_action=kwargs.get("trigger_action"),
                visual_state_id=decision.state_id,
                screenshot_path=shot_path,
                activity=activity,
                run_index=self.run_index,
            )
            for fp in placements:
                self.ad_catalog.observe(fp)
        except Exception:
            logger.exception("Ad placement detection failed (non-fatal)")
        return decision

    def _page_label(self, activity: str | None) -> str:
        if activity:
            short = activity.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
            short = short.replace("Activity", "").replace("Fragment", "") or short
            return short or "unknown"
        if self.graph.current_state and self.graph.current_state.label:
            return str(self.graph.current_state.label)
        return "unknown"


def run_ad_exploration(
    adb: AndroidADB,
    *,
    analysis: Any = None,
    package_name: str | None = None,
    activity: str | None = None,
    limits: ExplorationLimits | None = None,
    ad_limits: AdDiscoveryLimits | None = None,
    output_dir: str | Path | None = None,
    max_runs: int | None = None,
    reset_between_runs: bool = True,
) -> AdExplorationCampaign:
    """Run up to N exploration passes and merge unique ad placements."""
    prior: ExplorationPrior | None = None
    if analysis is not None:
        prior = prior_from_analysis(analysis)
    if prior is None:
        if not package_name:
            raise ExplorationEngineError(
                "Ad exploration requires analysis JSON or an explicit --package."
            )
        prior = prior_from_package(package_name, activity=activity)
    elif activity and not prior.launch_activity:
        prior.launch_activity = activity

    exploration_limits = limits or ExplorationLimits.from_settings()
    discovery_limits = ad_limits or AdDiscoveryLimits.from_settings()
    runs = max_runs if max_runs is not None else discovery_limits.max_exploration_runs
    runs = max(1, runs)

    application_intelligence = None
    if analysis is not None:
        try:
            from app.modules.apk_intelligence import build_application_intelligence

            application_intelligence = build_application_intelligence(analysis)
        except Exception:
            application_intelligence = None

    catalog = AdPlacementCatalog(discovery_limits)
    campaign = AdExplorationCampaign(
        package_name=prior.package_name,
        catalog=catalog,
    )
    started = time.perf_counter()
    launcher = AppLauncher(adb)

    log_explorer(
        "ad-campaign start package=%s runs=%s target/page=%s max/page=%s",
        prior.package_name,
        runs,
        discovery_limits.target_ad_variations_per_page,
        discovery_limits.max_ad_variations_per_page,
    )

    for run_index in range(runs):
        log_explorer("ad-campaign run %s/%s", run_index + 1, runs)
        if reset_between_runs and run_index > 0:
            try:
                # Soft resume between runs — avoid kill/open thrashing.
                launcher.resume_app(prior.package_name, prior.launch_activity)
                focus = launcher.current_component() or ""
                if "/" in focus:
                    prior.launch_activity = focus.split("/", 1)[1]
                time.sleep(max(1.0, exploration_limits.action_delay_ms / 1000.0))
            except Exception as exc:
                campaign.warnings.append(f"run {run_index} reset failed: {exc}")
                logger.warning("Failed to reset app between runs: %s", exc)

        engine = AdAwareExplorationEngine(
            adb,
            prior=prior,
            limits=exploration_limits,
            output_dir=output_dir,
            ad_catalog=catalog,
            run_index=run_index,
            prefer_ad_triggers=True,
            launcher=launcher,
            application_intelligence=application_intelligence,
        )
        try:
            session = engine.run()
        except ExplorationEngineError as exc:
            campaign.warnings.append(f"run {run_index} failed: {exc}")
            campaign.status = "partial"
            break

        campaign.run_sessions.append(session)
        campaign.runs_completed += 1
        campaign.warnings.extend(session.warnings)

        pages = catalog.pages() or []
        # Early-stop only on *strong* (SDK/id) evidence meeting the per-page target.
        eligible = [p for p in pages if catalog.strong_count_for_page(p) > 0]
        if eligible and all(catalog.has_reached_target(p) for p in eligible):
            campaign.stop_reason = "target_ad_variations_per_page"
            log_explorer("ad-campaign target reached for all pages — stopping early")
            break
    else:
        if not campaign.stop_reason:
            campaign.stop_reason = "max_exploration_runs"

    if not campaign.stop_reason:
        campaign.stop_reason = "completed"
    if campaign.unique_ad_placements == 0 and campaign.runs_completed:
        campaign.status = "partial"
        campaign.warnings.append("No advertisement placements were detected across runs.")
    elif campaign.status != "partial":
        campaign.status = "completed"

    campaign.duration_ms = int((time.perf_counter() - started) * 1000)
    log_explorer(
        "ad-campaign done status=%s unique_ads=%s runs=%s duration_ms=%s",
        campaign.status,
        campaign.unique_ad_placements,
        campaign.runs_completed,
        campaign.duration_ms,
    )
    return campaign


def fingerprint_to_schema_ad(fp) -> Any:
    """Map a Phase 5 fingerprint onto the public :class:`AdPlacement` schema."""
    from pathlib import Path

    from app.schemas.exploration import AdPlacement

    left, top, width, height = fp.relative_bbox
    coverage = max(0.0, min(1.0, float(width) * float(height)))
    shot = Path(fp.screenshot_path).name if fp.screenshot_path else None
    ad_type = fp.ad_type if fp.ad_type in {
        "banner",
        "interstitial",
        "native",
        "rewarded",
        "app_open",
        "unknown",
    } else "unknown"
    return AdPlacement(
        page=fp.page,
        ad_detected=fp.ad_detected,
        ad_type=ad_type,
        position=fp.position,
        relative_bbox=[float(left), float(top), float(width), float(height)],
        uniqueness_key=fp.uniqueness_key or None,
        trigger_action=fp.trigger_action,
        coverage_ratio=coverage,
        is_fullscreen=fp.position == "fullscreen" or coverage >= 0.55,
        detection_method="heuristic",
        confidence="MEDIUM" if fp.evidence else "LOW",
        state_id=fp.visual_state_id,
        screenshot_file=shot,
        evidence=list(fp.evidence),
    )


def campaign_to_exploration_result(campaign: AdExplorationCampaign):
    """Thin adapter: merged Phase 5 catalog → :class:`ExplorationResult` (no S3)."""
    from app.modules.exploration.explorer import session_to_exploration_result
    from app.schemas.exploration import ExplorationResult

    if campaign.run_sessions:
        base = session_to_exploration_result(campaign.run_sessions[-1])
    else:
        base = ExplorationResult(
            status="failed" if campaign.status == "failed" else "partial",
            reason=campaign.stop_reason or None,
            package_name=campaign.package_name,
        )

    placements = [
        fingerprint_to_schema_ad(record.fingerprint) for record in campaign.catalog.placements
    ]
    summary = base.summary.model_copy(
        update={
            "ads_detected": len(placements),
            "duration_ms": campaign.duration_ms or base.summary.duration_ms,
        }
    )
    status = campaign.status if campaign.status in {"completed", "partial", "skipped", "failed"} else base.status
    warnings = list(dict.fromkeys([*base.warnings, *campaign.warnings]))
    return ExplorationResult(
        status=status,
        reason=campaign.stop_reason or base.reason,
        package_name=campaign.package_name or base.package_name,
        launch_activity=base.launch_activity,
        device=base.device,
        summary=summary,
        states=base.states,
        screenshots=base.screenshots,
        ad_placements=placements,
        warnings=warnings,
    )
