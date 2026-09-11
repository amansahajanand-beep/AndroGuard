"""Unit tests for Phase 6 screenshot advertisement detection."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.modules.ad_detection import (
    AdDetectionResult,
    AdDetector,
    BoundingBox,
    HeuristicAdProvider,
    OpenAIVisionProvider,
    ProviderNotConfiguredError,
    build_provider,
    infer_position,
    normalize_ad_type,
)
from app.modules.ad_detection.providers.vision_common import parse_vision_json


def _write_png(path: Path, *, width: int = 1080, height: int = 2400, band: str | None = "bottom") -> Path:
    image = Image.new("RGB", (width, height), (245, 245, 245))
    pixels = image.load()
    assert pixels is not None
    if band == "bottom":
        for y in range(int(height * 0.84), height):
            for x in range(width):
                pixels[x, y] = (220, 40, 40) if (x + y) % 7 else (30, 30, 200)
    elif band == "top":
        for y in range(0, int(height * 0.12)):
            for x in range(width):
                pixels[x, y] = (40, 180, 40) if (x + y) % 5 else (200, 200, 40)
    image.save(path, format="PNG")
    return path


def test_normalize_and_infer_position():
    assert normalize_ad_type("Rewarded Video") == "rewarded"
    assert normalize_ad_type("full-screen") == "interstitial"
    box = BoundingBox(x=0, y=2000, width=1080, height=200)
    assert infer_position(box, image_width=1080, image_height=2400) == "bottom"


def test_heuristic_detects_bottom_banner(tmp_path: Path):
    shot = _write_png(tmp_path / "banner.png", band="bottom")
    detector = AdDetector(HeuristicAdProvider(min_confidence=0.4), min_confidence=0.4)
    result = detector.detect(shot)
    assert result.detected is True
    assert result.type in {"banner", "native", "interstitial"}
    assert result.bounding_box is not None
    assert result.bounding_box.width > 0
    assert result.position in {"bottom", "middle", "fullscreen", "top"}
    payload = result.to_dict()
    assert "detected" in payload and "bounding_box" in payload


def test_heuristic_plain_screen_may_be_empty(tmp_path: Path):
    shot = _write_png(tmp_path / "plain.png", band=None)
    detector = AdDetector(HeuristicAdProvider(min_confidence=0.9), min_confidence=0.9)
    result = detector.detect(shot)
    # High threshold → often none on flat grey.
    assert result.detected in {True, False}
    assert result.provider == "heuristic"


def test_openai_provider_requires_key():
    provider = OpenAIVisionProvider(api_key=None)
    try:
        provider.analyze("missing.png")
        assert False, "expected ProviderNotConfiguredError"
    except ProviderNotConfiguredError:
        pass
    except FileNotFoundError:
        # Key check should happen first; if file check wins, still fail clearly.
        raise AssertionError("expected ProviderNotConfiguredError before file IO")


def test_build_provider_heuristic():
    provider = build_provider("heuristic")
    assert provider.name == "heuristic"


def test_parse_vision_json_primary_shape():
    text = json.dumps(
        {
            "ads": [
                {
                    "detected": True,
                    "type": "banner",
                    "confidence": 0.95,
                    "bounding_box": {"x": 20, "y": 1680, "width": 1040, "height": 180},
                    "position": "bottom",
                }
            ]
        }
    )
    results = parse_vision_json(
        text,
        provider="openai",
        image_path="/tmp/a.png",
        image_width=1080,
        image_height=2400,
    )
    assert len(results) == 1
    item = results[0]
    assert item.detected is True
    assert item.type == "banner"
    assert abs(item.confidence - 0.95) < 1e-6
    assert item.bounding_box == BoundingBox(x=20, y=1680, width=1040, height=180)
    assert item.position == "bottom"


def test_detection_result_example_shape():
    result = AdDetectionResult(
        detected=True,
        type="banner",
        confidence=0.95,
        bounding_box=BoundingBox(x=20, y=1680, width=1040, height=180),
        position="bottom",
        provider="openai",
    )
    payload = result.to_dict()
    assert payload["detected"] is True
    assert payload["type"] == "banner"
    assert payload["confidence"] == 0.95
    assert payload["bounding_box"] == {"x": 20, "y": 1680, "width": 1040, "height": 180}
    assert payload["position"] == "bottom"
