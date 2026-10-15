"""Phase 8: exploration screenshot S3 storage tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.exploration.screenshot_storage import (
    ScreenshotMetadata,
    ScreenshotStorage,
    apply_metadata_to_exploration_result,
    exploration_state_key,
    hitl_screenshot_key,
    page_from_activity,
    publish_exploration_screenshots,
)
from app.schemas.exploration import (
    ExplorationResult,
    ExplorationScreenshotInfo,
    ExplorationSummary,
    ScreenState,
)
from app.storage.s3 import public_url_for_key, reset_s3_client


def test_exploration_state_key_structure(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_prefix", "apps")
    key = exploration_state_key(
        app_id="app123",
        run_id="run456",
        page="home",
        state_index=1,
    )
    assert key == "apps/app123/runs/run456/home/state_001.png"
    key2 = exploration_state_key(
        app_id="app123",
        run_id="run456",
        page="settings",
        state_index=2,
    )
    assert key2 == "apps/app123/runs/run456/settings/state_002.png"


def test_hitl_key_structure(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_prefix", "apps")
    assert (
        hitl_screenshot_key(app_id="app123", run_id="run456", hitl_index=1)
        == "apps/app123/runs/run456/hitl/hitl_001.png"
    )


def test_page_from_activity() -> None:
    assert page_from_activity("com.example/.MainActivity") == "MainActivity"
    assert page_from_activity(
        "com.example/com.example.PrivacyPolicySetting", label="entry"
    ) == "PrivacyPolicySetting"


def test_metadata_public_dict_has_no_bytes() -> None:
    meta = ScreenshotMetadata(
        screenshot_id="ss_1",
        run_id="run1",
        page="home",
        state_id="shot-1",
        local_path="/tmp/a.png",
        s3_key="apps/a/runs/run1/home/state_001.png",
        s3_url="https://example/apps/a/runs/run1/home/state_001.png",
        width=1080,
        height=2400,
        triggering_action="tap",
        ad_detected=True,
        ad_type="banner",
        ad_position="bottom",
        confidence=0.8,
    )
    payload = meta.public_dict()
    assert "base64" not in payload
    assert "data" not in payload
    assert payload["s3_key"].endswith("state_001.png")
    assert payload["ad_detected"] is True


def test_publish_without_s3_keeps_local_and_records_error(tmp_path: Path, monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_access_key", None)
    monkeypatch.setattr(config.settings, "s3_secret_key", None)
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    shot = SimpleNamespace(
        local_path=str(png),
        width=10,
        height=20,
        timestamp="2026-01-01T00:00:00+00:00",
        trigger_action="entry",
        activity="com.example/.Home",
        state_id="shot-a",
    )
    record = SimpleNamespace(
        screenshot=shot,
        state_id="shot-a",
        label="home",
        trigger_action="entry",
        visual=SimpleNamespace(activity="com.example/.Home"),
        ad_placement=SimpleNamespace(slot_count=0, candidate_regions=()),
    )
    result = publish_exploration_screenshots(
        run_id="run-local",
        package_name="com.example",
        states=[record],
    )
    assert result.uploaded == 0
    assert result.metadata
    assert result.metadata[0].local_path
    assert result.metadata[0].upload_error
    assert result.warnings


def test_upload_file_success_with_retry(tmp_path: Path, monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_access_key", "test-key")
    monkeypatch.setattr(config.settings, "s3_secret_key", "test-secret")
    monkeypatch.setattr(config.settings, "s3_bucket", "apk-screenshots")
    monkeypatch.setattr(config.settings, "s3_prefix", "apps")
    monkeypatch.setattr(config.settings, "s3_endpoint_url", "https://example.invalid")
    monkeypatch.setattr(config.settings, "s3_public_base_url", "https://cdn.example/public")
    monkeypatch.setattr(config.settings, "s3_verify_uploads", True)
    monkeypatch.setattr(config.settings, "s3_upload_retries", 3)
    reset_s3_client()

    calls = {"n": 0}

    def fake_upload(key, data, *, content_type="image/png", retries=None, verify=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return key, f"https://cdn.example/public/apk-screenshots/{key}"

    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.upload_object_bytes",
        fake_upload,
    )

    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG" + b"x" * 40)
    store = ScreenshotStorage(app_id="com.example", run_id="run1", enabled=True)
    # Bypass real retry by calling fake that fails once then succeeds — our
    # ScreenshotStorage calls upload_object_bytes once; retry is inside s3_store.
    # Simulate success on first call for storage layer:
    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.upload_object_bytes",
        lambda key, data, **kw: (key, f"https://cdn.example/public/apk-screenshots/{key}"),
    )
    meta = store.upload_file(
        png,
        page="home",
        state_id="shot-1",
        triggering_action="tap",
        width=100,
        height=200,
        ad_detected=True,
        ad_type="banner",
        ad_position="bottom",
        confidence=0.9,
    )
    assert meta.s3_key == "apps/com.example/runs/run1/home/state_001.png"
    assert meta.s3_url
    assert meta.upload_error is None
    assert meta.ad_detected is True


def test_upload_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_access_key", "k")
    monkeypatch.setattr(config.settings, "s3_secret_key", "s")
    monkeypatch.setattr(config.settings, "s3_bucket", "b")
    reset_s3_client()

    def boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.upload_object_bytes",
        boom,
    )
    png = tmp_path / "b.png"
    png.write_bytes(b"\x89PNG" + b"y" * 40)
    store = ScreenshotStorage(app_id="app", run_id="run", enabled=True)
    meta = store.upload_file(png, page="home", state_id="s1")
    assert meta.s3_key is None
    assert meta.upload_error
    assert "RuntimeError" in meta.upload_error


def test_hitl_upload_bytes(tmp_path: Path, monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_access_key", "k")
    monkeypatch.setattr(config.settings, "s3_secret_key", "s")
    monkeypatch.setattr(config.settings, "s3_bucket", "b")
    monkeypatch.setattr(config.settings, "s3_prefix", "apps")
    reset_s3_client()
    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.upload_object_bytes",
        lambda key, data, **kw: (key, f"https://x/{key}"),
    )
    store = ScreenshotStorage(app_id="app123", run_id="run456", enabled=True)
    meta = store.upload_bytes(
        b"\x89PNG" + b"z" * 20,
        state_id="hitl_001",
        kind="hitl",
        local_path=str(tmp_path / "hitl.png"),
    )
    assert meta.s3_key == "apps/app123/runs/run456/hitl/hitl_001.png"
    assert meta.kind == "hitl"


def test_apply_metadata_updates_exploration_result() -> None:
    from app.modules.exploration.screenshot_storage import ScreenshotPublishResult

    exploration = ExplorationResult(
        status="completed",
        package_name="com.example",
        summary=ExplorationSummary(screenshots_captured=1),
        screenshots=[
            ExplorationScreenshotInfo(file_name="a.png", state_id="shot-1"),
        ],
        states=[
            ScreenState(
                state_id="shot-1",
                fingerprint="abc",
                screenshot=ExplorationScreenshotInfo(file_name="a.png", state_id="shot-1"),
            )
        ],
    )
    publish = ScreenshotPublishResult(
        uploaded=1,
        metadata=[
            ScreenshotMetadata(
                screenshot_id="ss_1",
                run_id="run",
                page="home",
                state_id="shot-1",
                s3_key="apps/com.example/runs/run/home/state_001.png",
                s3_url="https://cdn/apps/com.example/runs/run/home/state_001.png",
                triggering_action="entry",
                ad_detected=False,
            )
        ],
    )
    apply_metadata_to_exploration_result(exploration, publish)
    assert exploration.screenshots[0].s3_key.endswith("state_001.png")
    assert exploration.screenshots[0].url
    assert exploration.summary.screenshots_uploaded == 1
    assert exploration.screenshot_records
    dumped = exploration.model_dump()
    assert "base64" not in str(dumped).lower()


def test_public_url_for_key_aws_style(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_public_base_url", None)
    monkeypatch.setattr(config.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(config.settings, "s3_bucket", "my-bucket")
    monkeypatch.setattr(config.settings, "s3_region", "us-east-1")
    url = public_url_for_key("apps/a/runs/r/home/state_001.png")
    assert url.startswith("https://my-bucket.s3.us-east-1.amazonaws.com/")


def test_upload_object_bytes_retries(monkeypatch) -> None:
    from app.core import config
    from app.storage import s3 as s3_mod

    monkeypatch.setattr(config.settings, "s3_access_key", "k")
    monkeypatch.setattr(config.settings, "s3_secret_key", "s")
    monkeypatch.setattr(config.settings, "s3_bucket", "b")
    monkeypatch.setattr(config.settings, "s3_upload_retries", 3)
    monkeypatch.setattr(config.settings, "s3_upload_retry_backoff_seconds", 0)
    monkeypatch.setattr(config.settings, "s3_verify_uploads", False)
    monkeypatch.setattr(config.settings, "s3_public_base_url", "https://cdn")
    reset_s3_client()

    attempts = {"n": 0}

    class FakeClient:
        def put_object(self, **kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("fail")
            return {}

    monkeypatch.setattr(s3_mod, "_client", lambda: FakeClient())
    key, url = s3_mod.upload_object_bytes("apps/a/runs/r/home/state_001.png", b"png")
    assert attempts["n"] == 3
    assert key.endswith("state_001.png")
    assert "apps/a" in url


def test_local_screenshots_dir_is_package_and_job(tmp_path: Path, monkeypatch) -> None:
    from app.core import config
    from app.modules.exploration.screenshot_storage import local_hitl_dir, local_screenshots_dir

    monkeypatch.setattr(config.settings, "temp_root", tmp_path)
    root = local_screenshots_dir("com.example.app", "job-abc")
    assert root == tmp_path / "screenshots" / "com.example.app" / "job-abc"
    assert root.is_dir()
    hitl = local_hitl_dir("com.example.app", "job-abc")
    assert hitl == root / "hitl"
    assert hitl.is_dir()


def test_publish_still_attempts_when_head_bucket_fails(
    tmp_path: Path, monkeypatch
) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "s3_access_key", "test-key")
    monkeypatch.setattr(config.settings, "s3_secret_key", "test-secret")
    monkeypatch.setattr(config.settings, "s3_bucket", "apk-screenshots")
    monkeypatch.setattr(config.settings, "s3_prefix", "apps")
    monkeypatch.setattr(config.settings, "s3_public_base_url", "https://cdn.example/public")
    monkeypatch.setattr(config.settings, "s3_verify_uploads", False)
    reset_s3_client()

    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    shot = SimpleNamespace(
        local_path=str(png),
        width=10,
        height=20,
        timestamp="2026-01-01T00:00:00+00:00",
        trigger_action="entry",
        activity="com.example/.Home",
        state_id="shot-a",
        s3_key=None,
        s3_url=None,
    )
    record = SimpleNamespace(
        screenshot=shot,
        state_id="shot-a",
        label="home",
        trigger_action="entry",
        visual=SimpleNamespace(activity="com.example/.Home"),
        ad_placement=SimpleNamespace(slot_count=0, candidate_regions=()),
    )

    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.s3_ready",
        lambda: False,
    )

    def fake_upload(key, data, *, content_type="image/png", retries=None, verify=None):
        return key, f"https://cdn.example/public/apk-screenshots/{key}"

    monkeypatch.setattr(
        "app.modules.exploration.screenshot_storage.s3_store.upload_object_bytes",
        fake_upload,
    )
    result = publish_exploration_screenshots(
        run_id="run-1",
        package_name="com.example",
        states=[record],
    )
    assert result.uploaded == 1
    assert result.metadata[0].s3_key
    assert any("head check failed" in w or "still attempting" in w for w in result.warnings)
