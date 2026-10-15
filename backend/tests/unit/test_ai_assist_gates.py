"""AI / auto-assist gate tests (permissions, default, ads, forms)."""

from __future__ import annotations

from app.modules.ai_explorer.assist import (
    AI_ASSISTABLE_TYPES,
    HITL_ONLY_TYPES,
    is_ai_assistable,
    plan_ad_dismiss_actions,
    plan_ai_assist_actions,
)
from app.modules.ai_explorer.schema import ALLOWED_ACTIONS, AIActionDecision
from app.modules.ai_explorer.validator import validate_and_map
from app.modules.exploration.action_planner import plan_actions
from app.modules.exploration.prior_knowledge import prior_from_package
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
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
        focusable=False,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def test_type_text_in_allowed_actions() -> None:
    assert "type_text" in ALLOWED_ACTIONS


def test_permissions_and_default_are_assistable() -> None:
    assert InterventionType.PERMISSION in AI_ASSISTABLE_TYPES
    assert InterventionType.DEFAULT_APP in AI_ASSISTABLE_TYPES
    assert InterventionType.TERMS_CONSENT in AI_ASSISTABLE_TYPES
    assert InterventionType.LOGIN in HITL_ONLY_TYPES
    assert is_ai_assistable(
        DetectionResult(required=True, type=InterventionType.PERMISSION, title="Allow")
    )
    assert not is_ai_assistable(
        DetectionResult(required=True, type=InterventionType.OTP, title="OTP")
    )


def test_plan_permission_prefers_allow() -> None:
    elements = [
        _el(text="Don't allow"),
        _el(text="Allow"),
        _el(text="While using the app"),
    ]
    planned = plan_ai_assist_actions(
        elements,
        detection=DetectionResult(
            required=True, type=InterventionType.PERMISSION, title="Permission"
        ),
    )
    assert planned
    assert planned[0].label.lower() in {"allow", "while using the app"}


def test_plan_default_app_prefers_cancel_not_set_default() -> None:
    """Never grant HOME during exploration — Cancel beats Set as default."""
    elements = [
        _el(text="Chrome"),
        _el(text="com.example.app"),
        _el(text="Set as default"),
        _el(text="Cancel"),
    ]
    planned = plan_ai_assist_actions(
        elements,
        detection=DetectionResult(
            required=True, type=InterventionType.DEFAULT_APP, title="Default"
        ),
        target_package="com.example.app",
    )
    assert planned
    assert planned[0].label.lower() == "cancel"
    assert all("set as default" not in (p.label or "").lower() for p in planned)


def test_plan_ad_dismiss_finds_close() -> None:
    elements = [
        _el(text="Install"),
        _el(text="Close"),
        _el(text="", resource_id="btn_close", bounds=(900, 20, 980, 90)),
    ]
    planned = plan_ad_dismiss_actions(elements, screen_size=(1080, 1920))
    assert planned
    assert all("install" not in (p.label or "").lower() for p in planned)


def test_create_alarm_types_then_prefers_save() -> None:
    """Empty name field → type first; filled name → Save wins."""
    empty = [
        _el(
            text="",
            resource_id="alarm_name",
            class_name="android.widget.EditText",
            focusable=True,
            clickable=True,
            bounds=(40, 200, 1000, 280),
        ),
        _el(
            text="Save",
            class_name="android.widget.Button",
            bounds=(900, 40, 1060, 120),
        ),
    ]
    detection = DetectionResult(
        required=True, type=InterventionType.CREATE_CONTENT, title="Create Alarm"
    )
    first = plan_ai_assist_actions(empty, detection=detection)
    assert first[0].kind == "type_text"

    filled = [
        _el(
            text="Test Item",
            resource_id="alarm_name",
            class_name="android.widget.EditText",
            focusable=True,
            clickable=True,
            bounds=(40, 200, 1000, 280),
        ),
        _el(
            text="Save",
            class_name="android.widget.Button",
            bounds=(900, 40, 1060, 120),
        ),
    ]
    second = plan_ai_assist_actions(filled, detection=detection, prefer_submit=True)
    assert second[0].kind == "tap"
    assert second[0].label.lower() == "save"
    assert second[0].meta.get("tag") == "submit_cta"


def test_plan_actions_excludes_install_cta() -> None:
    elements = [
        _el(text="Install", bounds=(100, 1800, 980, 2000), resource_id="id/install"),
        _el(text="Open settings", bounds=(40, 400, 400, 480)),
        _el(
            text="",
            content_description="Close",
            bounds=(980, 40, 1060, 120),
            resource_id="id/close",
            class_name="android.widget.ImageButton",
        ),
    ]
    prior = prior_from_package("com.example.app")
    planned = plan_actions(elements, prior=prior, screen_size=(1080, 2400), include_menu=False)
    taps = [item for item in planned if item.kind == "tap"]
    assert taps
    assert taps[0].meta.get("is_close") is True or "close" in taps[0].label.lower()
    assert all(item.label != "Install" for item in taps)


def test_plan_ai_assist_includes_type_text_and_cta() -> None:
    elements = [
        _el(
            text="",
            resource_id="name",
            class_name="android.widget.EditText",
            focusable=True,
            clickable=True,
        ),
        _el(text="Save", class_name="android.widget.Button"),
        _el(text="English", class_name="android.widget.TextView"),
    ]
    planned = plan_ai_assist_actions(
        elements,
        detection=DetectionResult(
            required=True, type=InterventionType.CREATE_CONTENT, title="Create"
        ),
    )
    kinds = {item.kind for item in planned}
    assert "type_text" in kinds
    assert "tap" in kinds


def test_validate_type_text_override() -> None:
    elements = [
        _el(
            text="",
            resource_id="title",
            class_name="android.widget.EditText",
            focusable=True,
            clickable=True,
        )
    ]
    candidates = plan_ai_assist_actions(
        elements,
        detection=DetectionResult(required=True, type=InterventionType.FORM_INPUT, title="Form"),
    )
    assert candidates
    key = next(c.key for c in candidates if c.kind == "type_text")
    planned = validate_and_map(
        {"action": "type_text", "target": key, "text": "My Alarm", "reason": "name field"},
        candidates,
    )
    assert planned.kind == "type_text"
    assert planned.action.text == "My Alarm"


def test_reject_dangerous_type_text() -> None:
    import pytest

    with pytest.raises(Exception):
        AIActionDecision.model_validate(
            {"action": "type_text", "target": "k", "text": "adb shell rm -rf /", "reason": "x"}
        )


def test_default_app_without_cancel_does_not_press_back() -> None:
    """DEFAULT_APP with no Cancel must soft-resume / skip — never Back to system Home."""
    from unittest.mock import MagicMock

    from app.modules.ai_explorer.assist import try_ai_assist

    ui = MagicMock()
    relaunch = MagicMock()
    cleared, notes = try_ai_assist(
        ui=ui,
        elements=[_el(text="Some App", bounds=(40, 400, 1000, 500))],
        detection=DetectionResult(
            required=True, type=InterventionType.DEFAULT_APP, title="Default"
        ),
        activity="com.example/.DefaultAppActivity",
        package_name="com.example.app",
        screen_size=(1080, 1920),
        relaunch=relaunch,
    )
    assert cleared is True
    assert any(
        "home_swipe_default_app" in n
        or "skip_default_app_no_back" in n
        or "relaunch_default_app" in n
        for n in notes
    )
    relaunch.assert_called_once()
    ui.perform.assert_not_called()
