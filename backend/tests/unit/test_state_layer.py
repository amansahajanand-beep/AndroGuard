"""Unit tests for Phase 3 screenshot hashing and state detection."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.modules.exploration.image_hasher import ImageHasher
from app.modules.exploration.screenshot_manager import CapturedScreenshot, ScreenshotManager
from app.modules.exploration.state_detector import (
    StateDetector,
    ad_placement_fingerprint,
    ui_structure_hash,
)
from app.modules.exploration.ui_element import UIElement
from tests.unit.test_emulator_layer import make_adb


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (120, 200), *, mark: bool = False) -> bytes:
    image = Image.new("RGB", size, color=color)
    if mark:
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 80, 110, 140), fill=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _shot_from_png(data: bytes, state_id: str, hasher: ImageHasher) -> CapturedScreenshot:
    perceptual = hasher.hash_bytes(data)
    with Image.open(BytesIO(data)) as image:
        width, height = image.size
    return CapturedScreenshot(
        state_id=state_id,
        local_path=f"/tmp/{state_id}.png",
        width=width,
        height=height,
        image_hash=perceptual.hex,
        timestamp="2026-01-01T00:00:00+00:00",
        activity="com.example/.Main",
        trigger_action="test",
        ahash=perceptual.ahash,
        dhash=perceptual.dhash,
        byte_size=len(data),
    )


# --- ImageHasher -------------------------------------------------------------


def test_similar_images_score_high():
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)
    base = _png_bytes((30, 120, 200))
    # One-pixel noise in the corner should not invent a new state.
    noisy = bytearray(_png_bytes((30, 120, 200)))
    # Re-encode with a tiny edit instead of corrupting PNG bytes.
    image = Image.open(BytesIO(base)).convert("RGB")
    image.putpixel((0, 0), (31, 120, 200))
    buf = BytesIO()
    image.save(buf, format="PNG")
    noisy_png = buf.getvalue()

    left = hasher.hash_bytes(base)
    right = hasher.hash_bytes(noisy_png)
    assert hasher.similarity(left, right) >= 0.9
    assert hasher.is_similar(left, right, threshold=0.9)


def test_different_images_score_low():
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)
    left = hasher.hash_bytes(_png_bytes((10, 10, 10)))
    right = hasher.hash_bytes(_png_bytes((240, 240, 10), mark=True))
    assert hasher.similarity(left, right) < 0.85


def test_status_bar_crop_reduces_clock_sensitivity():
    hasher = ImageHasher(hash_size=8, crop_top=0.1, crop_bottom=0.0)
    image_a = Image.new("RGB", (100, 200), color=(40, 40, 40))
    image_b = image_a.copy()
    # Paint different "clock" pixels only in the top strip.
    for x in range(100):
        image_a.putpixel((x, 2), (255, 255, 0))
        image_b.putpixel((x, 2), (0, 255, 255))
    # Same content below the crop.
    for y in range(30, 200):
        for x in range(100):
            image_a.putpixel((x, y), (20, 90, 160))
            image_b.putpixel((x, y), (20, 90, 160))

    def encode(img: Image.Image) -> bytes:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    sim = hasher.similarity(hasher.hash_bytes(encode(image_a)), hasher.hash_bytes(encode(image_b)))
    assert sim >= 0.95


# --- UI / ad fingerprints ----------------------------------------------------


def test_ui_structure_hash_ignores_text_changes():
    a = [
        UIElement(
            text="12:01",
            resource_id="com.app:id/title",
            class_name="android.widget.TextView",
            bounds=(0, 100, 200, 150),
            clickable=False,
            visible=True,
        )
    ]
    b = [
        UIElement(
            text="12:02",
            resource_id="com.app:id/title",
            class_name="android.widget.TextView",
            bounds=(0, 100, 200, 150),
            clickable=False,
            visible=True,
        )
    ]
    assert ui_structure_hash(a) == ui_structure_hash(b)


def test_ad_placement_fingerprint_detects_banner_band_and_webview():
    elements = [
        UIElement(
            class_name="android.webkit.WebView",
            resource_id="com.app:id/ad_banner",
            bounds=(0, 2200, 1080, 2400),
            visible=True,
            clickable=True,
        ),
        UIElement(
            class_name="android.widget.FrameLayout",
            resource_id="com.app:id/content",
            bounds=(0, 0, 1080, 2200),
            visible=True,
        ),
    ]
    fp = ad_placement_fingerprint(elements, screen_width=1080, screen_height=2400)
    assert fp.slot_count >= 1
    assert fp.layout_hash
    assert any(r["reason"] in {"class_hint", "resource_id_hint", "banner_band"} for r in fp.candidate_regions)


# --- StateDetector -----------------------------------------------------------


def test_state_detector_retains_unique_and_dedupes_similar(tmp_path: Path):
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)
    detector = StateDetector(hasher=hasher, similarity_threshold=0.9)

    blue = _shot_from_png(_png_bytes((20, 80, 180)), "s1", hasher)
    blue2 = _shot_from_png(_png_bytes((20, 80, 180)), "s2", hasher)
    red = _shot_from_png(_png_bytes((200, 30, 30), mark=True), "s3", hasher)

    first = detector.observe(blue, retain=True, trigger_action="open")
    second = detector.observe(blue2, retain=True, trigger_action="wait")
    third = detector.observe(red, retain=True, trigger_action="tap")

    assert first.is_new is True
    assert second.is_new is False
    assert second.matched_state_id == first.state_id
    assert third.is_new is True
    assert len(detector.states) == 2


def test_compare_screenshots_separates_visual_and_ad_layout():
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)
    detector = StateDetector(hasher=hasher, similarity_threshold=0.9)

    left = _shot_from_png(_png_bytes((10, 10, 10)), "a", hasher)
    right = _shot_from_png(_png_bytes((10, 10, 10)), "b", hasher)
    # Same ad webview band on both, different "content" text only in hierarchy.
    shared_ad = UIElement(
        class_name="com.google.android.gms.ads.AdView",
        resource_id="com.app:id/banner",
        bounds=(0, 0, 100, 40),
        visible=True,
    )
    left_ui = [shared_ad, UIElement(text="Score 1", class_name="android.widget.TextView", bounds=(0, 50, 80, 80), visible=True)]
    right_ui = [shared_ad, UIElement(text="Score 99", class_name="android.widget.TextView", bounds=(0, 50, 80, 80), visible=True)]

    result = detector.compare_screenshots(left, right, left_elements=left_ui, right_elements=right_ui)
    assert result["same_visual_state"] is True
    assert result["ui_structure_match"] is True
    assert result["same_ad_placement_state"] is True


# --- ScreenshotManager (mocked adb) ------------------------------------------


def test_screenshot_manager_capture_writes_png(tmp_path: Path):
    png = _png_bytes((50, 50, 50), size=(64, 128))
    adb, runner = make_adb({})

    def binary_runner(args, timeout):  # noqa: ANN001
        # Bypass FakeRunner text path: ScreenshotManager uses run_binary/screencap_png.
        from app.modules.exploration.adb import CommandResult

        joined = " ".join(args)
        runner.calls.append(list(args))
        if "screencap" in joined:
            return png
        return CommandResult(tuple(args), 0, "", "", 1)

    # Patch run_binary directly.
    adb.run_binary = lambda args, timeout=None, with_serial=True: png  # type: ignore[method-assign]
    adb.screencap_png = lambda timeout=None: png  # type: ignore[method-assign]

    manager = ScreenshotManager(adb, output_dir=tmp_path)
    shot = manager.capture(trigger_action="manual", resolve_activity=False)
    assert Path(shot.local_path).is_file()
    assert shot.width == 64 and shot.height == 128
    assert shot.trigger_action == "manual"
    assert shot.image_hash
    assert shot.to_dict()["state_id"] == shot.state_id


def test_png_crlf_repair_helper():
    from app.modules.exploration.adb import _repair_png_bytes

    good = b"\x89PNG\r\n\x1a\n" + b"rest"
    assert _repair_png_bytes(good) == good
    corrupted = b"\x89PNG\r\n\r\n\x1a\n" + b"x"
    # After replacing CRLF with LF we should recover a PNG signature prefix.
    fixed = _repair_png_bytes(corrupted)
    assert fixed.startswith(b"\x89PNG")
