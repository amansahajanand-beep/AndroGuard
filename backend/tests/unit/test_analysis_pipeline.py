from __future__ import annotations

from app.jobs.models import JobRecord, JobStage, JobStatus, progress_for
from app.modules.exploration.launcher import LaunchOutcome
from app.modules.exploration.target import LaunchTarget
from app.schemas.exploration import DeviceInfo
from app.services.analysis_pipeline import to_exploration_result
from app.workers.emulator_stage import DeviceStageResult


def _completed_stage() -> DeviceStageResult:
    return DeviceStageResult(
        status="completed",
        device=DeviceInfo(serial="emulator-5554", android_version="14", sdk_int=34),
        target=LaunchTarget("com.example", "com.example.Main", "static_analysis"),
        installed_now=True,
        launch=LaunchOutcome(
            package_name="com.example",
            activity="com.example.Main",
            component="com.example/com.example.Main",
            method="am_start",
            foreground=True,
            duration_ms=1200,
            warnings=[],
        ),
        emulator_serial="emulator-5554",
        duration_ms=45000,
    )


def test_completed_stage_maps_to_partial_without_engine():
    exploration = to_exploration_result(_completed_stage())
    assert exploration.status == "partial"
    assert exploration.package_name == "com.example"
    assert exploration.launch_activity == "com.example.Main"
    assert exploration.device.serial == "emulator-5554"
    assert exploration.summary.duration_ms == 45000
    assert exploration.reason is not None


def test_completed_stage_without_engine_is_partial():
    exploration = to_exploration_result(_completed_stage())
    assert exploration.status == "partial"
    assert "exploration engine did not run" in (exploration.reason or "")


def test_failed_stage_maps_to_failed_exploration():
    stage = DeviceStageResult(
        status="failed",
        error={"code": "EMULATOR_BOOT_TIMEOUT", "message": "did not boot"},
        target=LaunchTarget("com.example", None, "static_analysis_partial"),
        duration_ms=240000,
    )
    exploration = to_exploration_result(stage)
    assert exploration.status == "failed"
    assert exploration.reason == "did not boot"
    assert exploration.package_name == "com.example"


def test_exploration_serializes_into_analysis_payload():
    from app.schemas.analysis import AnalysisData

    data = AnalysisData.model_validate(
        {
            "apk": {"file_name": "a.apk", "file_size": 1, "sha256": "x"},
            "manifest": {},
            "sdk": {},
            "analysis": {
                "status": "completed",
                "analyzed_at": "now",
                "analyzer_version": "1.0.0",
                "duration_ms": 1,
            },
        }
    )
    assert "exploration" not in data.model_dump()

    data.exploration = to_exploration_result(_completed_stage())
    payload = data.model_dump()
    assert payload["exploration"]["status"] == "partial"
    assert payload["exploration"]["device"]["serial"] == "emulator-5554"


# --- Job progress reporting --------------------------------------------------


def test_stage_progress_is_monotonic():
    ordered = [
        JobStage.QUEUED,
        JobStage.STATIC_ANALYSIS,
        JobStage.EMULATOR_BOOT,
        JobStage.APK_INSTALL,
        JobStage.APP_LAUNCH,
        JobStage.EXPLORING,
        JobStage.AD_ANALYSIS,
        JobStage.UPLOADING,
        JobStage.PERSISTING,
        JobStage.DONE,
    ]
    values = [progress_for(stage) for stage in ordered]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100


def test_processing_payload_reports_progress_without_result():
    record = JobRecord(
        id="job-1",
        status=JobStatus.PROCESSING,
        stage=JobStage.APK_INSTALL,
        progress=progress_for(JobStage.APK_INSTALL),
    )
    body = record.public_payload()
    assert body == {
        "job_id": "job-1",
        "status": "processing",
        "stage": "apk_install",
        "progress": 35,
    }


def test_completed_payload_exposes_analysis_and_screenshots():
    record = JobRecord(
        id="job-2",
        status=JobStatus.COMPLETED,
        stage=JobStage.DONE,
        progress=100,
        file_name="demo.apk",
        package_name="com.demo",
        result={
            "schema_version": "1.0.0",
            "status": "completed",
            "data": {
                "apk": {"file_name": "demo.apk", "package_name": "com.demo"},
                "exploration": {"status": "completed", "states": []},
            },
        },
    )
    body = record.public_payload()
    assert body["status"] == "completed"
    assert body["schema_version"] == "1.0.0"
    assert body["json_analysis"]["data"]["exploration"]["status"] == "completed"
    assert body["screenshots"]["status"] == "completed"
    assert body["success"] is True
    assert body["apk"]["package"] == "com.demo"
    assert "pages" in body["screenshots"]


def test_failed_payload_exposes_error():
    record = JobRecord(
        id="job-3",
        status=JobStatus.FAILED,
        error_code="INVALID_APK",
        error_message="bad apk",
    )
    body = record.public_payload()
    assert body["error"] == {"code": "INVALID_APK", "message": "bad apk"}
