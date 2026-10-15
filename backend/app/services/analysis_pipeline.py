from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.emulator_lock import emulator_session
from app.core.errors import AppError
from app.jobs.models import JobStage, JobStatus
from app.jobs.store import get_job_store
from app.schemas.analysis import AnalysisResponse, AppSubmission
from app.schemas.exploration import ExplorationResult, ExplorationSummary
from app.services.analysis_service import analyze_apk
from app.services.ai_report import attach_ai_review
from app.services.artifacts import publish_static_artifacts
from app.storage.local import LocalTempStorage
from app.workers.emulator_stage import DeviceStageResult, run_device_stage

logger = logging.getLogger(__name__)


def run_analysis_job(
    job_id: str,
    *,
    apk_path: Path,
    file_name: str,
    file_size: int,
    sha256: str,
    submission: AppSubmission | None = None,
    explore: bool = True,
    storage: LocalTempStorage | None = None,
) -> dict:
    """Run the full pipeline for one job: static analysis, then the device stage.

    Executed by a worker thread, never inside an HTTP handler. Static analysis is
    always completed and persisted first, so a failing emulator can never cost
    the caller their JSON.
    """
    store = get_job_store()
    storage = storage or LocalTempStorage()

    def announce(stage: JobStage) -> None:
        try:
            store.mark_stage(job_id, stage)
        except Exception:
            logger.warning("Could not record stage %s for job %s", stage, job_id, exc_info=True)

    try:
        announce(JobStage.STATIC_ANALYSIS)
        result = analyze_apk(
            apk_path,
            file_name=file_name,
            file_size=file_size,
            sha256=sha256,
            job_id=job_id,
            storage=storage,
            submission=submission,
        )
        try:
            store.update(job_id, package_name=result.data.apk.package_name)
        except Exception:
            logger.debug("Could not record package name for %s", job_id, exc_info=True)

        # The APK on disk is the exact upload from this request; the device stage
        # installs that same file.
        result.data.exploration = _run_exploration(
            job_id,
            apk_path=apk_path,
            result=result,
            explore=explore,
            announce=announce,
        )

        exploration = result.data.exploration
        if exploration is not None and exploration.status not in {"skipped", "failed"}:
            announce(JobStage.AD_ANALYSIS)
            try:
                from app.services.ad_enrichment import enrich_exploration_ads

                enrich_exploration_ads(exploration)
            except Exception:
                logger.exception("Phase 9 ad enrichment failed for job %s", job_id)
                exploration.warnings.append("Ad enrichment failed; continuing with partial ad data.")

        announce(JobStage.PERSISTING)
        attach_ai_review(
            result,
            policy_text=submission.privacy_policy_text if submission else None,
            policy_error=submission.privacy_policy_error if submission else None,
        )
        job_record = store.get(job_id)
        publish_static_artifacts(
            job_id,
            result,
            storage,
            user_id=job_record.user_id if job_record is not None else None,
        )

        payload = result.model_dump()
        exploration = result.data.exploration
        hitl_reason = (exploration.reason or "") if exploration else ""
        explore_status = (exploration.status if exploration else None)

        if hitl_reason == "stopped_by_human":
            store.update(
                job_id,
                status=JobStatus.CANCELLED,
                stage=JobStage.DONE,
                progress=100,
                result=payload,
                finished_at=datetime.now(timezone.utc),
                intervention=None,
            )
        elif hitl_reason == "hitl_timeout":
            store.update(
                job_id,
                status=JobStatus.TIMEOUT,
                stage=JobStage.DONE,
                progress=100,
                result=payload,
                finished_at=datetime.now(timezone.utc),
            )
        elif explore_status == "failed":
            # Static APK JSON succeeded — never mark the whole job FAILED.
            store.update(
                job_id,
                status=JobStatus.PARTIAL,
                stage=JobStage.DONE,
                progress=100,
                result=payload,
                finished_at=datetime.now(timezone.utc),
                intervention=None,
            )
        elif explore_status == "partial":
            store.update(
                job_id,
                status=JobStatus.PARTIAL,
                stage=JobStage.DONE,
                progress=100,
                result=payload,
                finished_at=datetime.now(timezone.utc),
                intervention=None,
            )
        else:
            store.mark_completed(job_id, payload)
        return payload

    except AppError as exc:
        logger.error("Job %s failed [%s]: %s", job_id, exc.code, exc.message)
        store.mark_failed(job_id, exc.code, exc.message)
        raise
    except Exception as exc:
        logger.exception("Job %s failed unexpectedly", job_id)
        store.mark_failed(job_id, "ANALYZER_ERROR", str(exc))
        raise
    finally:
        # Only now is the upload safe to remove: the emulator needed it.
        storage.delete_apk(job_id)


def _run_exploration(
    job_id: str,
    *,
    apk_path: Path,
    result: AnalysisResponse,
    explore: bool,
    announce,
) -> ExplorationResult:
    """Boot/install/launch, then run the Phase 4 explorer when the device is ready.

    Phase 8 publishes exploration screenshots to S3 best-effort after the
    session ends (upload failures become warnings / partial metadata).

    Phase 11 persists screenshot_runs / screenshots / human_interventions when
    PostgreSQL is configured (best-effort; never fails the job).
    """
    if not explore:
        return ExplorationResult.skipped("Exploration was not requested for this job.")
    if not settings.exploration_enabled:
        return ExplorationResult.skipped(
            "Exploration is disabled. Set EXPLORATION_ENABLED=true to enable it."
        )

    from app.modules.exploration.adb import AndroidADB
    from app.modules.exploration.emulator import EmulatorManager
    from app.modules.exploration.errors import ExplorationError
    from app.modules.exploration.explorer import run_exploration, session_to_exploration_result
    from app.modules.exploration.launcher import AppLauncher

    with emulator_session(job_id):
        # Keep the app + emulator alive so Phase 4 can drive the UI.
        # HITL waits hold this same lock so no other job can steal the device.
        preferred_serial = None
        try:
            from app.core.emulator_lock import current_slot

            slot = current_slot(job_id)
            if slot is not None and slot.adb_serial:
                preferred_serial = slot.adb_serial
        except Exception:
            preferred_serial = None

        # Cooperative cancel before expensive device work.
        try:
            from app.workers.job_runner import is_job_cancel_requested

            if is_job_cancel_requested(job_id):
                return ExplorationResult.failed("Job cancelled before device stage.")
        except Exception:
            pass

        stage = run_device_stage(
            apk_path,
            analysis=result,
            progress=announce,
            preferred_serial=preferred_serial,
            keep_app_running=True,
            stop_emulator=False,
        )
        if not stage.ok:
            exploration = to_exploration_result(stage)
            result.data.analysis.warnings.append(
                "Static analysis completed but the emulator stage did not: "
                f"{(stage.error or {}).get('message', 'unknown error')}"
            )
            if settings.emulator_stop_when_done:
                try:
                    EmulatorManager().stop()
                except Exception:
                    logger.warning("Could not stop emulator after failed device stage", exc_info=True)
            return exploration

        announce(JobStage.EXPLORING)
        exploration: ExplorationResult
        hitl_manager = None
        package_name = stage.target.package_name if stage.target else None
        try:
            serial = stage.emulator_serial
            if not serial:
                raise ExplorationError("NO_DEVICE", "Device stage completed without a serial.")
            adb = AndroidADB(serial=serial)

            # Phase 11: open screenshot_run before exploration / HITL.
            try:
                from app.db.phase11_repository import start_screenshot_run
                from app.modules.exploration.screenshot_storage import app_id_from_package

                start_screenshot_run(
                    run_id=job_id,
                    app_id=app_id_from_package(package_name, job_id=job_id),
                    job_id=job_id,
                    status="running",
                )
            except Exception:
                logger.debug("Phase 11 start_screenshot_run skipped", exc_info=True)

            if settings.hitl_enabled:
                from app.modules.hitl import InterventionDetector, InterventionManager, register_manager
                from app.modules.exploration.screenshot_storage import local_hitl_dir

                hitl_manager = InterventionManager(
                    job_id,
                    detector=InterventionDetector(
                        target_package=package_name
                    ),
                    run_id=job_id,
                    artifact_dir=local_hitl_dir(package_name, job_id),
                )
                register_manager(hitl_manager)

            session = run_exploration(
                adb,
                analysis=result,
                job_id=job_id,
                hitl_manager=hitl_manager,
            )
            exploration = session_to_exploration_result(session)
            exploration.device = stage.device
            exploration.warnings = list(dict.fromkeys([*stage.warnings, *exploration.warnings]))

            # Phase 8: publish screenshots to S3 (best-effort).
            announce(JobStage.UPLOADING)
            publish = None
            try:
                from app.modules.exploration.screenshot_storage import (
                    apply_metadata_to_exploration_result,
                    publish_exploration_screenshots,
                )

                from app.modules.exploration.ad_dwell import frame_publish_records

                publish = publish_exploration_screenshots(
                    run_id=job_id,
                    package_name=session.package_name or package_name,
                    states=[
                        *session.detector_states,
                        *frame_publish_records(session.ad_frames, session.ad_timelines),
                    ],
                )
                apply_metadata_to_exploration_result(exploration, publish)
            except Exception:
                logger.exception("Phase 8 screenshot upload failed for job %s", job_id)
                exploration.warnings.append(
                    "Exploration screenshots were not uploaded to S3 (partial result)."
                )

            # Phase 11: persist screenshot metadata + complete the run.
            try:
                from app.db.phase11_repository import (
                    complete_screenshot_run,
                    persist_screenshots_for_run,
                    summarize_publish_metadata,
                )

                meta_items = list(getattr(publish, "metadata", None) or [])
                persist_screenshots_for_run(run_id=job_id, items=meta_items)
                totals = summarize_publish_metadata(meta_items)
                run_status = "completed"
                if (exploration.status or "").lower() in {"failed", "error"}:
                    run_status = "failed"
                elif (exploration.status or "").lower() in {"partial", "stopped"}:
                    run_status = "partial"
                complete_screenshot_run(
                    run_id=job_id,
                    status=run_status,
                    **totals,
                )
            except Exception:
                logger.exception("Phase 11 screenshot persistence failed for job %s", job_id)

            # Copy Phase 5 catalog placements onto screen states when available.
            try:
                _attach_session_ad_placements(session, exploration)
            except Exception:
                logger.debug("Could not attach session ad placements", exc_info=True)

            logger.info(
                "Exploration completed for job %s: unique_states=%s actions=%s reason=%s",
                job_id,
                session.unique_states,
                session.actions_performed,
                session.stop_reason,
            )
        except ExplorationError as exc:
            logger.error("Exploration failed for job %s [%s]: %s", job_id, exc.code, exc.message)
            exploration = ExplorationResult.failed(exc.message)
            exploration.package_name = package_name
            exploration.launch_activity = (
                stage.launch.activity
                if stage.launch
                else (stage.target.activity if stage.target else None)
            )
            exploration.device = stage.device
            exploration.warnings = list(stage.warnings)
            result.data.analysis.warnings.append(
                f"Static analysis completed but exploration failed: {exc.message}"
            )
            try:
                from app.db.phase11_repository import complete_screenshot_run

                complete_screenshot_run(run_id=job_id, status="failed")
            except Exception:
                logger.debug("Phase 11 fail complete skipped", exc_info=True)
        except Exception as exc:
            logger.exception("Unexpected exploration failure for job %s", job_id)
            exploration = ExplorationResult.failed(str(exc))
            exploration.package_name = package_name
            exploration.device = stage.device
            exploration.warnings = list(stage.warnings)
            result.data.analysis.warnings.append(
                f"Static analysis completed but exploration failed: {exc}"
            )
            try:
                from app.db.phase11_repository import complete_screenshot_run

                complete_screenshot_run(run_id=job_id, status="failed")
            except Exception:
                logger.debug("Phase 11 fail complete skipped", exc_info=True)
        finally:
            if hitl_manager is not None:
                try:
                    from app.modules.hitl import unregister_manager

                    unregister_manager(job_id)
                except Exception:
                    logger.debug("HITL manager unregister failed", exc_info=True)
            package = package_name
            if package and stage.emulator_serial:
                try:
                    AppLauncher(AndroidADB(serial=stage.emulator_serial)).force_stop(package)
                except Exception:
                    logger.warning("Could not force-stop %s after exploration", package, exc_info=True)
            if settings.emulator_stop_when_done:
                try:
                    EmulatorManager().stop()
                except Exception:
                    logger.warning("Could not stop the emulator after exploration", exc_info=True)

    return exploration


def _attach_session_ad_placements(session: Any, exploration: ExplorationResult) -> None:
    """Map Phase 3/5 layout fingerprints from the session onto exploration states."""
    from app.schemas.exploration import AdPlacement, Bounds

    by_id = {record.state_id: record for record in session.detector_states}
    for state in exploration.states:
        if state.ad_placements:
            continue
        record = by_id.get(state.state_id)
        if record is None:
            continue
        fingerprint = getattr(record, "ad_placement", None)
        regions = list(getattr(fingerprint, "candidate_regions", ()) or ())
        for region in regions:
            if not isinstance(region, dict):
                continue
            bounds = None
            raw_bounds = region.get("bounds")
            if isinstance(raw_bounds, (list, tuple)) and len(raw_bounds) >= 4:
                left, top, right, bottom = (int(raw_bounds[0]), int(raw_bounds[1]), int(raw_bounds[2]), int(raw_bounds[3]))
                bounds = Bounds(left=left, top=top, right=right, bottom=bottom)
            elif isinstance(raw_bounds, dict):
                bounds = Bounds(
                    left=int(raw_bounds.get("left") or 0),
                    top=int(raw_bounds.get("top") or 0),
                    right=int(raw_bounds.get("right") or 0),
                    bottom=int(raw_bounds.get("bottom") or 0),
                )
            placement = AdPlacement(
                page=state.label or _page_label(state.activity),
                ad_detected=True,
                ad_type=(region.get("ad_type") or region.get("type") or "unknown"),  # type: ignore[arg-type]
                position=region.get("position"),
                relative_bbox=list(region["relative_bbox"])
                if isinstance(region.get("relative_bbox"), (list, tuple))
                else None,
                bounds=bounds,
                state_id=state.state_id,
                screenshot_file=state.screenshot.file_name if state.screenshot else None,
                detection_method="ui_tree",
                confidence="MEDIUM",
                evidence=list(region.get("evidence") or []),
            )
            state.ad_placements.append(placement)
            exploration.ad_placements.append(placement)
        if state.screenshot and state.ad_placements:
            primary = state.ad_placements[0]
            state.screenshot.ad_detected = True
            state.screenshot.ad_type = primary.ad_type
            state.screenshot.ad_position = primary.position


def _page_label(activity: str | None) -> str | None:
    if not activity:
        return None
    short = activity.rsplit("/", 1)[-1]
    return short.rsplit(".", 1)[-1]


def to_exploration_result(stage: DeviceStageResult) -> ExplorationResult:
    """Adapt a failed/partial Phase 1 device stage onto the exploration schema."""
    warnings = list(stage.warnings)
    if not stage.ok:
        error = stage.error or {}
        exploration = ExplorationResult.failed(
            error.get("message") or "The emulator stage failed."
        )
    else:
        exploration = ExplorationResult(
            status="partial",
            reason="Device stage completed but the exploration engine did not run.",
        )

    exploration.package_name = stage.target.package_name if stage.target else None
    exploration.launch_activity = (
        stage.launch.activity if stage.launch else (stage.target.activity if stage.target else None)
    )
    exploration.device = stage.device
    exploration.summary = ExplorationSummary(duration_ms=stage.duration_ms)
    exploration.warnings = warnings
    return exploration
