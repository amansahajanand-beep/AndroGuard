"""Phase 12A — Observation model + builder unit tests."""

from __future__ import annotations

import json

from app.modules.ad_detection.models import AdDetectionResult, BoundingBox
from app.modules.exploration.observation import Observation
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.ui_element import UIElement
from app.modules.hitl.intervention_types import DetectionResult, InterventionType


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.TextView",
        package="com.example.app",
        bounds=(0, 0, 100, 80),
        clickable=False,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=False,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def test_basic_observation() -> None:
    elements = [
        _el(text="Home", clickable=True, bounds=(40, 2000, 200, 2200)),
        _el(text="Settings", clickable=True, bounds=(800, 80, 1000, 160)),
        _el(text="Welcome", clickable=False, bounds=(40, 200, 600, 280)),
    ]
    obs = build_observation(
        package_name="com.example.app",
        activity="com.example.app/.MainActivity",
        elements=elements,
        screen_size=(1080, 2400),
        state_id="state_12",
        screenshot_path="/tmp/shot.png",
        screenshot_id="shot-abc",
        metadata={"source": "test"},
    )
    assert obs.package_name == "com.example.app"
    assert obs.activity == "com.example.app/.MainActivity"
    assert obs.state_id == "state_12"
    assert obs.screen_width == 1080
    assert obs.screen_height == 2400
    assert obs.screenshot_path == "/tmp/shot.png"
    assert obs.screenshot_id == "shot-abc"
    assert "Home" in obs.visible_text
    assert "Welcome" in obs.visible_text
    assert len(obs.clickable_elements) == 2
    assert len(obs.ui_elements) == 3
    assert obs.webview_detected is False
    assert obs.metadata["source"] == "test"


def test_no_ads() -> None:
    obs = build_observation(
        package_name="com.example.app",
        activity="Main",
        elements=[],
        ad_results=None,
    )
    assert obs.detected_ads == []


def test_ad_detected() -> None:
    ad = AdDetectionResult(
        detected=True,
        type="banner",
        confidence=0.94,
        bounding_box=BoundingBox(x=0, y=2000, width=1080, height=200),
        position="bottom",
        provider="heuristic",
        image_path="/tmp/shot.png",
        evidence=["banner_band"],
        raw={"internal": "drop_me"},
    )
    obs = build_observation(ad_results=[ad])
    assert len(obs.detected_ads) == 1
    assert obs.detected_ads[0]["detected"] is True
    assert obs.detected_ads[0]["type"] == "banner"
    assert obs.detected_ads[0]["confidence"] == 0.94
    assert obs.detected_ads[0]["position"] == "bottom"
    assert "raw" not in obs.detected_ads[0]


def test_hitl_detected() -> None:
    hitl = DetectionResult(
        required=True,
        type=InterventionType.LOGIN,
        title="Login / Sign in",
        message="Sign in required",
        confidence=0.91,
        is_system_ui=False,
    )
    obs = build_observation(hitl=hitl)
    assert obs.hitl_required is True
    assert obs.hitl_type == "login"
    assert obs.hitl_message == "Sign in required"
    assert obs.hitl["required"] is True
    assert obs.hitl["confidence"] == 0.91
    assert obs.hitl["is_system_ui"] is False


def test_webview_detected() -> None:
    elements = [
        _el(
            class_name="android.webkit.WebView",
            clickable=True,
            bounds=(0, 0, 1080, 1800),
        )
    ]
    obs = build_observation(elements=elements)
    assert obs.webview_detected is True


def test_missing_optional_information() -> None:
    obs = build_observation(
        package_name="com.example.app",
        activity=None,
        elements=None,
        screen_size=None,
        screenshot=None,
        ad_results=None,
        hitl=None,
    )
    assert obs.activity is None
    assert obs.screenshot_path is None
    assert obs.detected_ads == []
    assert obs.hitl_required is False
    assert obs.ui_elements == []
    assert obs.observation_id.startswith("obs_")


def test_serialization_json_dumps() -> None:
    obs = build_observation(
        package_name="com.example.app",
        activity="Main",
        elements=[_el(text="OK", clickable=True)],
        screen_size=(1080, 2400),
        state_id="s1",
        ad_results=[
            AdDetectionResult(detected=True, type="interstitial", confidence=0.8)
        ],
        hitl=DetectionResult(required=False),
    )
    payload = obs.to_dict()
    encoded = json.dumps(payload)
    assert "com.example.app" in encoded
    assert "observation_id" in payload
    assert isinstance(payload["clickable_elements"], list)


def test_observation_dataclass_defaults() -> None:
    obs = Observation()
    assert obs.hitl_required is False
    assert obs.detected_ads == []
    assert "required" in obs.to_dict()["hitl"]
