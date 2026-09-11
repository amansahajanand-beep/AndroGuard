"""Unit tests for Phase 2 UIAutomator inspection + action layer."""

from __future__ import annotations

import pytest

from app.modules.exploration.actions import (
    BackAction,
    CoordinateTapAction,
    HomeAction,
    SwipeAction,
    TapAction,
    WaitAction,
)
from app.modules.exploration.adb import CommandResult
from app.modules.exploration.errors import UiActionError, UiDumpError, UiParseError
from app.modules.exploration.ui_controller import UIController
from app.modules.exploration.ui_dump import filter_elements, parse_bounds, parse_ui_hierarchy
from app.modules.exploration.ui_element import UIElement
from tests.unit.test_emulator_layer import make_adb

SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="com.example.app" content-desc="" checkable="false" checked="false"
        clickable="false" enabled="true" focusable="false" focused="false"
        scrollable="false" long-clickable="false" password="false" selected="false"
        bounds="[0,0][1080,2400]" visible-to-user="true">
    <node index="0" text="Play" resource-id="com.example:id/play"
          class="android.widget.Button" package="com.example.app"
          content-desc="Play button" checkable="false" checked="false"
          clickable="true" enabled="true" focusable="true" focused="false"
          scrollable="false" long-clickable="false" password="false" selected="false"
          bounds="[100,500][500,650]" visible-to-user="true" />
    <node index="1" text="More" resource-id="com.example:id/more"
          class="android.widget.TextView" package="com.example.app"
          content-desc="" checkable="false" checked="false"
          clickable="false" enabled="true" focusable="false" focused="false"
          scrollable="true" long-clickable="false" password="false" selected="false"
          bounds="[0,1800][1080,2400]" visible-to-user="true" />
    <node index="2" text="Hidden" resource-id="com.example:id/hidden"
          class="android.widget.TextView" package="com.other"
          content-desc="" checkable="false" checked="false"
          clickable="true" enabled="false" focusable="false" focused="false"
          scrollable="false" long-clickable="false" password="false" selected="false"
          bounds="[10,10][10,10]" visible-to-user="false" />
  </node>
</hierarchy>
"""


# --- parser ------------------------------------------------------------------


def test_parse_bounds_happy_path():
    assert parse_bounds("[100,500][500,650]") == (100, 500, 500, 650)


def test_parse_bounds_rejects_garbage():
    with pytest.raises(UiParseError):
        parse_bounds("100,500,500,650")


def test_parse_ui_hierarchy_extracts_structured_elements():
    elements = parse_ui_hierarchy(SAMPLE_XML)
    assert len(elements) == 4

    play = next(item for item in elements if item.resource_id == "com.example:id/play")
    assert play.to_dict() == {
        "text": "Play",
        "resource_id": "com.example:id/play",
        "content_description": "Play button",
        "class_name": "android.widget.Button",
        "package": "com.example.app",
        "bounds": [100, 500, 500, 650],
        "clickable": True,
        "enabled": True,
        "scrollable": False,
        "visible": True,
        "checkable": False,
        "checked": False,
        "focusable": True,
        "focused": False,
        "long_clickable": False,
        "selected": False,
        "index": 0,
    }
    assert play.center == (300, 575)


def test_parse_ui_hierarchy_strips_status_prefix():
    prefixed = "UI hierchary dumped to: /sdcard/window_dump.xml\n" + SAMPLE_XML
    elements = parse_ui_hierarchy(prefixed)
    assert any(item.text == "Play" for item in elements)


def test_parse_ui_hierarchy_rejects_empty_and_invalid():
    with pytest.raises(UiParseError):
        parse_ui_hierarchy("")
    with pytest.raises(UiParseError):
        parse_ui_hierarchy("<not-closed>")


def test_filter_elements_by_package_and_clickable():
    elements = parse_ui_hierarchy(SAMPLE_XML)
    clickable = filter_elements(elements, package="com.example.app", clickable_only=True, enabled_only=True)
    assert [item.text for item in clickable] == ["Play"]

    visible = filter_elements(elements, visible_only=True)
    assert all(item.visible for item in visible)
    assert not any(item.resource_id.endswith("hidden") for item in visible)


def test_uielement_label_prefers_text_then_desc_then_id():
    assert UIElement(text="Go").label() == "Go"
    assert UIElement(content_description="Close").label() == "Close"
    assert UIElement(resource_id="a:id/x").label() == "a:id/x"


# --- actions -----------------------------------------------------------------


def test_tap_action_uses_element_center():
    adb, runner = make_adb({"input tap": (0, "", "")})
    element = UIElement(
        text="Play",
        resource_id="com.example:id/play",
        class_name="android.widget.Button",
        bounds=(100, 500, 500, 650),
        clickable=True,
        enabled=True,
    )
    result = TapAction(element=element).execute(adb)
    assert result.ok is True
    assert result.kind == "tap"
    assert "input tap 300 575" in runner.commands()
    assert result.meta["resource_id"] == "com.example:id/play"


def test_tap_action_rejects_disabled_or_empty_bounds():
    adb, _ = make_adb({})
    disabled = UIElement(text="X", bounds=(0, 0, 10, 10), enabled=False)
    with pytest.raises(UiActionError):
        TapAction(element=disabled).execute(adb)

    empty = UIElement(text="Y", bounds=(5, 5, 5, 5), enabled=True)
    with pytest.raises(UiActionError):
        TapAction(element=empty).execute(adb)


def test_coordinate_tap_and_key_actions():
    adb, runner = make_adb(
        {
            "input tap 12 34": (0, "", ""),
            "input keyevent 4": (0, "", ""),
            "input keyevent 3": (0, "", ""),
        }
    )
    assert CoordinateTapAction(12, 34).execute(adb).kind == "coordinate_tap"
    assert BackAction().execute(adb).kind == "back"
    assert HomeAction().execute(adb).kind == "home"
    commands = runner.commands()
    assert "input tap 12 34" in commands
    assert "input keyevent 4" in commands
    assert "input keyevent 3" in commands


def test_swipe_action_derives_directional_points():
    adb, runner = make_adb({"input swipe": (0, "", "")})
    result = SwipeAction(direction="up", duration_ms=250).execute(adb, screen_size=(1000, 2000))
    assert result.ok is True
    # inset 0.2 -> y from 1600 to 400 at x=500
    assert "input swipe 500 1600 500 400 250" in runner.commands()

    SwipeAction(direction="left").execute(adb, screen_size=(1000, 2000))
    assert "input swipe 800 1000 200 1000 300" in runner.commands()


def test_swipe_action_requires_screen_size_for_direction():
    adb, _ = make_adb({})
    with pytest.raises(UiActionError):
        SwipeAction(direction="down").execute(adb, screen_size=None)


def test_wait_action_does_not_call_adb():
    adb, runner = make_adb({})
    result = WaitAction(seconds=0).execute(adb)
    assert result.ok is True
    assert result.kind == "wait"
    assert runner.calls == []


# --- UIController ------------------------------------------------------------


def test_ui_controller_dump_ui_parses_device_xml():
    responses = {
        "uiautomator dump": (0, "UI hierchary dumped to: /sdcard/window_dump.xml\n", ""),
        "exec-out cat /sdcard/window_dump.xml": (0, SAMPLE_XML, ""),
    }
    adb, runner = make_adb(responses)
    controller = UIController(adb)
    dump = controller.dump_ui(package="com.example.app")
    assert dump.path == "/sdcard/window_dump.xml"
    assert len(dump.elements) == 3  # filtered out com.other
    assert any(item.text == "Play" for item in dump.elements)
    assert "uiautomator dump /sdcard/window_dump.xml" in runner.commands()


def test_ui_controller_dump_falls_back_to_shell_cat():
    responses = {
        "uiautomator dump": (0, "UI hierarchy dumped to: /sdcard/window_dump.xml\n", ""),
        "exec-out cat": (1, "", "exec-out failed"),
        "cat /sdcard/window_dump.xml": (0, SAMPLE_XML, ""),
    }
    adb, _ = make_adb(responses)
    dump = UIController(adb).dump_ui()
    assert len(dump.elements) == 4


def test_ui_controller_dump_raises_on_uiautomator_failure():
    adb, _ = make_adb({"uiautomator dump": (1, "", "ERROR: could not get idle state.")})
    with pytest.raises(UiDumpError) as excinfo:
        UIController(adb).dump_ui()
    assert excinfo.value.stderr == "ERROR: could not get idle state."


def test_ui_controller_gestures_delegate_to_actions():
    responses = {
        "input tap 10 20": (0, "", ""),
        "input tap 300 575": (0, "", ""),
        "input swipe": (0, "", ""),
        "input keyevent 4": (0, "", ""),
        "input keyevent 3": (0, "", ""),
        "wm size": (0, "Physical size: 1080x2400\n", ""),
        "wm density": (0, "Physical density: 420\n", ""),
        "getprop": (0, "1\n", ""),
    }
    adb, runner = make_adb(responses)
    controller = UIController(adb)

    play = UIElement(
        text="Play",
        resource_id="com.example:id/play",
        class_name="android.widget.Button",
        bounds=(100, 500, 500, 650),
        clickable=True,
        enabled=True,
    )
    assert controller.tap_element(play).ok is True
    assert controller.tap_coordinates(10, 20).ok is True
    assert controller.swipe_up().ok is True
    assert controller.swipe_down().ok is True
    assert controller.swipe_left().ok is True
    assert controller.swipe_right().ok is True
    assert controller.press_back().ok is True
    assert controller.press_home().ok is True
    assert controller.wait(0).ok is True

    commands = runner.commands()
    assert "input tap 300 575" in commands
    assert "input tap 10 20" in commands
    assert "input keyevent 4" in commands
    assert "input keyevent 3" in commands
    assert "input swipe" in commands
