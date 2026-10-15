"""Phase 9 unified analyze-apk response tests."""

from __future__ import annotations

from app.jobs.models import JobRecord, JobStage, JobStatus, progress_for
from app.services.unified_result import (
    build_screenshots_section,
    enrich_job_public_payload,
    public_job_status,
)


def test_public_status_maps_running_to_processing() -> None:
    assert public_job_status("running") == "processing"
    assert public_job_status("processing") == "processing"
    assert public_job_status("waiting_for_human") == "waiting_for_human"
    assert public_job_status("partial") == "partial"


def test_processing_payload_uses_phase9_status() -> None:
    record = JobRecord(
        id="job-1",
        status=JobStatus.PROCESSING,
        stage=JobStage.APK_INSTALL,
        progress=progress_for(JobStage.APK_INSTALL),
    )
    body = record.public_payload()
    assert body["status"] == "processing"
    assert body["progress"] == 35
    assert "json_analysis" not in body


def test_screenshots_section_groups_by_page() -> None:
    exploration = {
        "status": "completed",
        "states": [
            {
                "state_id": "home_state_004",
                "label": "Home",
                "activity": "com.example/.MainActivity",
                "screenshot": {
                    "screenshot_id": "home_001",
                    "state_id": "home_state_004",
                    "s3_key": "apps/app123/runs/run456/home/state_001.png",
                    "url": "https://cdn/apps/app123/runs/run456/home/state_001.png",
                    "width": 1080,
                    "height": 1920,
                },
                "ad_placements": [
                    {
                        "ad_detected": True,
                        "ad_type": "banner",
                        "position": "bottom",
                        "confidence": "HIGH",
                        "bounds": {"left": 20, "top": 1680, "right": 1060, "bottom": 1860},
                    }
                ],
            },
            {
                "state_id": "settings_1",
                "label": "Settings",
                "activity": "com.example/.Settings",
                "screenshot": {
                    "screenshot_id": "settings_001",
                    "s3_key": "apps/app123/runs/run456/settings/state_001.png",
                    "width": 1080,
                    "height": 1920,
                },
                "ad_placements": [],
            },
        ],
    }
    section = build_screenshots_section(exploration)
    assert section["status"] == "completed"
    assert section["total"] == 2
    assert len(section["pages"]) == 2
    home = next(p for p in section["pages"] if p["page"] == "Home")
    shot = home["screenshots"][0]
    assert shot["id"] == "home_001"
    assert shot["s3_key"].endswith("home/state_001.png")
    assert shot["ad"]["detected"] is True
    assert shot["ad"]["type"] == "banner"
    assert shot["ad"]["bounding_box"] == {
        "x": 20,
        "y": 1680,
        "width": 1040,
        "height": 180,
    }
    assert "base64" not in str(section).lower()


def test_screenshots_failed_when_exploration_failed() -> None:
    section = build_screenshots_section(
        {"status": "failed", "reason": "emulator boot timeout", "states": []}
    )
    assert section["status"] == "failed"
    assert section["error"] == "emulator boot timeout"
    assert section["total"] == 0
    assert section["pages"] == []


def test_completed_unified_payload_preserves_json_analysis() -> None:
    result = {
        "schema_version": "1.0.0",
        "status": "completed",
        "data": {
            "apk": {"file_name": "myapp.apk", "package_name": "com.example.myapp"},
            "manifest": {"package": "com.example.myapp"},
            "permissions": [{"name": "CAMERA"}],
            "exploration": {
                "status": "completed",
                "states": [
                    {
                        "state_id": "s1",
                        "label": "Home",
                        "screenshot": {
                            "screenshot_id": "home_001",
                            "s3_key": "apps/com.example.myapp/runs/job/home/state_001.png",
                        },
                        "ad_placements": [],
                    }
                ],
            },
        },
    }
    record = JobRecord(
        id="analysis_123",
        status=JobStatus.COMPLETED,
        stage=JobStage.DONE,
        progress=100,
        file_name="myapp.apk",
        package_name="com.example.myapp",
        result=result,
    )
    body = record.public_payload()
    assert body["success"] is True
    assert body["status"] == "completed"
    assert body["apk"] == {"name": "myapp.apk", "package": "com.example.myapp"}
    assert body["analysis"]["apk"]["package_name"] == "com.example.myapp"
    assert "exploration" not in body["analysis"]
    assert body["json_analysis"]["schema_version"] == "1.0.0"
    assert body["screenshots"]["total"] == 1
    assert body["screenshots"]["pages"][0]["page"] == "Home"
    assert body["exploration"]["status"] == "completed"


def test_partial_when_static_ok_exploration_failed() -> None:
    result = {
        "schema_version": "1.0.0",
        "status": "completed",
        "data": {
            "apk": {"file_name": "x.apk", "package_name": "com.x"},
            "exploration": {"status": "failed", "reason": "device offline", "states": []},
        },
    }
    record = JobRecord(
        id="job-partial",
        status=JobStatus.PARTIAL,
        stage=JobStage.DONE,
        progress=100,
        result=result,
        file_name="x.apk",
        package_name="com.x",
    )
    body = record.public_payload()
    assert body["status"] == "partial"
    assert body["success"] is True
    assert body["analysis"]["apk"]["package_name"] == "com.x"
    assert body["screenshots"]["status"] == "failed"
    assert "device offline" in (body["screenshots"]["error"] or "")


def test_waiting_for_human_payload_keeps_intervention() -> None:
    record = JobRecord(
        id="job-hitl",
        status=JobStatus.WAITING_FOR_HUMAN,
        stage=JobStage.WAITING_FOR_HUMAN,
        progress=55,
        intervention={
            "id": "hitl_456",
            "type": "default_app",
            "type_label": "Default App",
            "title": "Set application as default",
            "message": "Please complete this action in the emulator.",
            "suggested_action": "Choose the default app (or cancel) in the emulator",
            "screenshot": "/shot.png",
        },
    )
    body = record.public_payload()
    assert body["status"] == "waiting_for_human"
    assert body["intervention"]["id"] == "hitl_456"
    assert body["intervention"]["suggested_action"]
    assert "json_analysis" not in body


def test_enrich_does_not_strip_legacy_fields() -> None:
    body = {"job_id": "j", "status": "completed", "stage": "done", "progress": 100}
    result = {
        "schema_version": "1.0.0",
        "status": "completed",
        "data": {
            "apk": {"file_name": "a.apk", "package_name": "com.a"},
            "exploration": {"status": "completed", "states": []},
        },
    }
    out = enrich_job_public_payload(body, result=result, file_name="a.apk", package_name="com.a")
    assert out["json_analysis"] is result
    assert out["screenshots"]["pages"] == []
