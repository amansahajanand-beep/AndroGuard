"""Unit tests for Phase 4 exploration (prior knowledge, planner, graph, engine)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image

from app.modules.exploration.action_planner import plan_actions
from app.modules.exploration.explorer import ExplorationEngine, ExplorationLimits
from app.modules.exploration.image_hasher import ImageHasher
from app.modules.exploration.navigation_graph import NavigationGraph
from app.modules.exploration.prior_knowledge import prior_from_analysis, prior_from_package
from app.modules.exploration.screenshot_manager import CapturedScreenshot
from app.modules.exploration.state_detector import ScreenStateRecord, StateDetector, VisualFingerprint
from app.modules.exploration.state_detector import AdLayoutFingerprint
from app.modules.exploration.ui_controller import UiDump
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.actions import ActionResult


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.Button",
        package="com.example.app",
        bounds=(0, 0, 100, 80),
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def _png(color: tuple[int, int, int], *, band: int = 0) -> bytes:
    image = Image.new("RGB", (240, 400), color=color)
    if band:
        for y in range(80, 320):
            for x in range(40, 200):
                image.putpixel((x, y), (min(255, color[0] + band), color[1], color[2]))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _shot(state_id: str, color: tuple[int, int, int], *, band: int = 0) -> CapturedScreenshot:
    data = _png(color, band=band)
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)
    perceptual = hasher.hash_bytes(data)
    return CapturedScreenshot(
        state_id=state_id,
        local_path=f"/tmp/{state_id}.png",
        width=240,
        height=400,
        image_hash=perceptual.hex,
        timestamp="2026-01-01T00:00:00+00:00",
        activity="com.example/.Main",
        trigger_action="test",
        ahash=perceptual.ahash,
        dhash=perceptual.dhash,
        byte_size=len(data),
        package_name="com.example.app",
    )


# --- Prior knowledge ---------------------------------------------------------


def test_prior_from_analysis_uses_activities_and_launcher():
    analysis = {
        "data": {
            "apk": {"package_name": "com.example.app"},
            "manifest": {"package": "com.example.app"},
            "activities": [
                {
                    "name": "com.example.app.SplashActivity",
                    "enabled": True,
                    "intent_filters": [],
                },
                {
                    "name": "com.example.app.SettingsActivity",
                    "enabled": True,
                    "intent_filters": [
                        {
                            "actions": ["android.intent.action.MAIN"],
                            "categories": ["android.intent.category.LAUNCHER"],
                        }
                    ],
                },
                {
                    "name": "com.example.app.ProfileActivity",
                    "enabled": True,
                    "intent_filters": [],
                },
            ],
        }
    }
    prior = prior_from_analysis(analysis)
    assert prior is not None
    assert prior.package_name == "com.example.app"
    assert prior.launch_activity == "com.example.app.SettingsActivity"
    assert "settings" in prior.preferred_labels
    assert "profile" in prior.preferred_labels


def test_prior_label_priority_prefers_matching_buttons():
    prior = prior_from_package(
        "com.example.app",
        activity="com.example.app.SettingsActivity",
        activities=["com.example.app.SettingsActivity", "com.example.app.GamesActivity"],
    )
    assert prior.label_priority("Open Settings", "id/settings") > prior.label_priority("Random", "id/foo")


# --- Action planner ----------------------------------------------------------


def test_is_home_launcher_detects_nexus():
    from app.modules.exploration.action_planner import is_home_launcher

    assert is_home_launcher(
        "com.google.android.apps.nexuslauncher/com.google.android.apps.nexuslauncher.NexusLauncherActivity"
    )
    assert is_home_launcher(None, "com.android.launcher3")
    assert not is_home_launcher(
        "com.reader.alldocviewer.pdfeditor/.MainActivity",
        "com.reader.alldocviewer.pdfeditor",
    )


def test_app_launcher_home_is_not_system_home():
    from app.modules.exploration.action_planner import is_home_launcher

    activity = (
        "com.reader.alldocviewer.pdfeditor/"
        "com.reader.alldocviewer.pdfeditor.launcher.LauncherHomeActivity"
    )
    assert not is_home_launcher(
        activity,
        "com.reader.alldocviewer.pdfeditor",
        target_package="com.reader.alldocviewer.pdfeditor",
    )


def test_plan_actions_deprioritizes_search_chrome():
    from app.modules.exploration.action_planner import plan_actions

    elements = [
        _el(
            text="Search",
            resource_id="com.reader.alldocviewer.pdfeditor:id/ivLens",
            content_description="Search",
            bounds=(900, 200, 1000, 280),
        ),
        _el(
            text="Files",
            resource_id="com.reader.alldocviewer.pdfeditor:id/files",
            bounds=(100, 800, 400, 900),
        ),
    ]
    planned = plan_actions(
        elements,
        screen_size=(1080, 2400),
        include_menu=False,
        activity="com.reader.alldocviewer.pdfeditor/.launcher.LauncherHomeActivity",
    )
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert "Files" in (taps[0].label or taps[0].meta.get("text") or "")


def test_content_launch_skips_default_app_activity():
    from app.modules.exploration.explorer import ExplorationEngine
    from app.modules.exploration.prior_knowledge import prior_from_package
    from unittest.mock import MagicMock

    prior = prior_from_package("com.example.app", activity=".DefaultAppActivity")
    prior.activities = [
        "com.example.app.DefaultAppActivity",
        "com.example.app.MainActivity",
    ]
    prior.launch_activity = "com.example.app.DefaultAppActivity"
    engine = ExplorationEngine(MagicMock(), prior=prior)
    assert engine._content_launch_activity() == "com.example.app.MainActivity"


def test_plan_actions_orders_prior_labels_first():
    prior = prior_from_package(
        "com.example.app",
        activities=["com.example.app.SettingsActivity"],
    )
    elements = [
        _el(text="Help", bounds=(10, 400, 200, 480), resource_id="id/help"),
        _el(text="Settings", bounds=(10, 200, 200, 280), resource_id="id/settings"),
        _el(text="About", bounds=(10, 300, 200, 380), resource_id="id/about"),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=(1080, 2400), include_menu=False)
    taps = [item for item in planned if item.kind == "tap"]
    assert taps[0].label == "Settings"


def test_plan_actions_adds_wait_when_no_clickables():
    elements = [
        _el(text="Splash", clickable=False, bounds=(0, 0, 1080, 2400), class_name="android.widget.ImageView")
    ]
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False)
    assert any(item.kind == "wait" for item in planned)
    # Idle splash must not burn budget on blind screen swipes.
    assert not any(item.kind.startswith("swipe_") for item in planned)


def test_plan_actions_prefers_close_over_install_on_interstitial():
    screen = (1080, 2400)
    elements = [
        _el(
            text="Install",
            bounds=(100, 2000, 980, 2200),
            resource_id="id/install",
            package="com.reader.alldocviewer.pdfeditor",
        ),
        _el(
            text="",
            content_description="Close",
            bounds=(980, 40, 1060, 120),
            resource_id="id/close",
            class_name="android.widget.ImageButton",
            package="com.reader.alldocviewer.pdfeditor",
        ),
        _el(
            text="Open settings",
            bounds=(40, 400, 400, 480),
            package="com.reader.alldocviewer.pdfeditor",
        ),
    ]
    prior = prior_from_package("com.reader.alldocviewer.pdfeditor")
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=False)
    taps = [item for item in planned if item.kind == "tap"]
    assert taps, "expected tap actions"
    assert taps[0].meta.get("is_close") is True or "close" in taps[0].label.lower()
    install = [item for item in taps if item.label == "Install"]
    # Install CTA should be dropped or ranked below close.
    if install:
        assert taps[0].priority > install[0].priority
    assert taps[0].label != "Install"


def test_plan_actions_prefers_permission_dialog_buttons():
    elements = [
        _el(text="Settings", package="com.example.app", bounds=(10, 800, 200, 880)),
        _el(
            text="While using the app",
            package="com.android.permissioncontroller",
            bounds=(100, 1400, 980, 1520),
            resource_id="com.android.permissioncontroller:id/permission_allow_foreground_only_button",
        ),
    ]
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False)
    taps = [item for item in planned if item.kind == "tap"]
    assert taps[0].label == "While using the app"


def test_plan_actions_includes_swipe_for_scrollable():
    elements = [
        _el(
            text="Browse",
            clickable=True,
            bounds=(10, 100, 200, 180),
        ),
        _el(
            text="",
            clickable=False,
            scrollable=True,
            bounds=(0, 200, 1080, 2000),
            class_name="android.widget.ScrollView",
        ),
    ]
    planned = plan_actions(elements, screen_size=(1080, 2400), include_menu=False, include_wait_if_empty=False)
    kinds = {item.kind for item in planned}
    assert "swipe_up" in kinds
    assert "swipe_down" in kinds
    taps = [item for item in planned if item.kind == "tap"]
    swipes = [item for item in planned if item.kind.startswith("swipe_")]
    # With labeled taps present, swipes must rank below them.
    assert taps and swipes
    assert taps[0].priority > swipes[0].priority


def test_plan_actions_skips_banner_ad_prefers_back_and_create():
    screen = (1080, 1920)
    elements = [
        _el(
            text="",
            content_description="Navigate up",
            bounds=(40, 60, 140, 160),
            class_name="android.widget.ImageButton",
            resource_id="id/back",
        ),
        _el(text="Language", bounds=(40, 220, 1000, 320)),
        _el(text="Theme", bounds=(40, 340, 1000, 440)),
        _el(
            text="Add",
            content_description="Create alarm",
            bounds=(880, 1600, 1020, 1740),
            class_name="android.widget.ImageButton",
            resource_id="id/fab_add",
        ),
        # Google test banner at bottom — must never be tapped.
        _el(
            text="",
            bounds=(0, 1780, 1080, 1920),
            class_name="android.webkit.WebView",
            resource_id="id/ad_view",
            clickable=True,
        ),
        _el(
            text="Test Ad",
            bounds=(200, 1800, 500, 1880),
            clickable=False,
            class_name="android.widget.TextView",
        ),
        _el(
            text="This is a 468x60 test ad.",
            bounds=(200, 1860, 900, 1905),
            clickable=False,
            class_name="android.widget.TextView",
        ),
    ]
    prior = prior_from_package("com.wakeup.timer.alarmclock")
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=False)
    taps = [item for item in planned if item.kind == "tap"]
    assert taps
    assert not any("ad_view" in ((item.meta or {}).get("resource_id") or "") for item in taps)
    assert any(item.meta.get("is_create_explore") for item in taps)
    assert any(item.meta.get("is_nav_back") for item in taps)
    assert taps[0].meta.get("is_create_explore") or taps[0].meta.get("is_nav_back")


def test_relaunch_action_kind():
    from app.modules.exploration.action_planner import relaunch_action

    planned = relaunch_action(reason="system_home")
    assert planned.kind == "relaunch"
    assert "home" in planned.key
    assert planned.meta.get("prefer_home_swipe") is True


def test_recover_from_system_home_prefers_swipe_right():
    """On emulator Home, enter default app via swipe-right — not cold relaunch first."""
    from app.modules.exploration.prior_knowledge import ExplorationPrior

    prior = ExplorationPrior(
        package_name="com.example.app",
        launch_activity="com.example.app.MainActivity",
    )
    adb = MagicMock()
    engine = ExplorationEngine(adb, prior=prior)
    engine.ui = MagicMock()
    engine.ui.swipe_right.return_value = ActionResult(kind="swipe", ok=True)
    engine.launcher = MagicMock()
    # First checks: still on system home; after swipe: target foreground.
    engine.launcher.is_foreground.side_effect = [False, False, True]
    engine.launcher.current_component.return_value = (
        "com.example.app/com.example.app.MainActivity"
    )
    engine._settle = MagicMock()  # type: ignore[method-assign]
    engine._relaunch_target = MagicMock()  # type: ignore[method-assign]

    ok = engine._recover_from_system_home()
    assert ok is True
    assert engine.ui.swipe_right.called
    engine._relaunch_target.assert_not_called()


# --- Navigation graph --------------------------------------------------------


def test_navigation_graph_tree_and_backtrack():
    graph = NavigationGraph()
    hasher = ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0)

    def record(sid: str, color: tuple[int, int, int]) -> ScreenStateRecord:
        shot = _shot(sid, color)
        return ScreenStateRecord(
            state_id=sid,
            visual=VisualFingerprint(
                image_hash=shot.image_hash,
                ahash=shot.ahash,
                dhash=shot.dhash,
                ui_structure_hash="x",
                activity="act",
            ),
            ad_placement=AdLayoutFingerprint(layout_hash="", slot_count=0),
            screenshot=shot,
            label=sid,
        )

    home = record("home", (10, 10, 10))
    settings = record("settings", (20, 20, 20))
    profile = record("profile", (30, 30, 30))

    graph.add_state(home, parent_id=None, label="Home")
    graph.add_state(settings, parent_id="home", label="Settings")
    graph.add_state(profile, parent_id="home", label="Profile")
    graph.connect(from_state_id="home", to_state_id="settings", action_kind="tap", action_key="tap:settings")
    graph.mark_action("home", "tap:settings")

    assert graph.unique_child_count("home") == 2
    assert graph.parent_state_id == "profile" or graph.current_state_id == "profile"
    tree = graph.ascii_tree()
    assert "Home" in tree
    assert "Settings" in tree
    parent = graph.backtrack_parent()
    assert parent == "home"
    assert graph.current_state_id == "home"


# --- Exploration engine (mocked device) --------------------------------------


def test_exploration_engine_discovers_unique_states_and_stops():
    prior = prior_from_package("com.example.app", activity="com.example.app.MainActivity")
    limits = ExplorationLimits(
        target_states_per_page=5,
        max_states_per_page=10,
        max_actions=20,
        max_time_seconds=30,
        max_depth=5,
        max_unique_states=3,
        action_delay_ms=0,
        stabilize_ms=0,
        splash_wait_seconds=0.0,
    )

    screen_elements = [
        [_el(text="Go A", resource_id="id/a", bounds=(10, 100, 200, 180))],
        [_el(text="Go B", resource_id="id/b", bounds=(10, 100, 200, 180))],
        [_el(text="Go C", resource_id="id/c", bounds=(10, 100, 200, 180))],
        [_el(text="Done", resource_id="id/d", bounds=(10, 100, 200, 180))],
    ]
    shot_specs = [
        ((20, 20, 20), 0),
        ((200, 30, 30), 80),
        ((30, 200, 30), 120),
        ((30, 30, 200), 160),
    ]
    phase = {"n": 0}

    ui = MagicMock()
    ui.settle_ms = 0

    def dump_ui(**kwargs):
        idx = min(phase["n"], len(screen_elements) - 1)
        return UiDump(
            elements=screen_elements[idx],
            xml="<hier/>",
            path="/sdcard/x.xml",
            duration_ms=1,
            package_filter="com.example.app",
        )

    ui.dump_ui.side_effect = dump_ui
    ui.screen_size.return_value = (1080, 2400)

    def perform(action):
        phase["n"] = min(phase["n"] + 1, len(screen_elements) - 1)
        return ActionResult(kind=getattr(action, "kind", "tap"), ok=True, detail="ok")

    ui.perform.side_effect = perform
    ui.press_back.return_value = ActionResult(kind="back", ok=True, detail="ok")

    screenshots = MagicMock()

    def capture(**kwargs):
        idx = min(phase["n"], len(shot_specs) - 1)
        color, band = shot_specs[idx]
        return _shot(f"auto-{idx}", color, band=band)

    screenshots.capture.side_effect = capture

    launcher = MagicMock()
    launcher.is_foreground.return_value = True
    launcher.current_component.return_value = "com.example.app/.MainActivity"
    launcher.current_package.return_value = "com.example.app"

    adb = MagicMock()
    engine = ExplorationEngine(
        adb,
        prior=prior,
        limits=limits,
        ui=ui,
        screenshots=screenshots,
        detector=StateDetector(
            hasher=ImageHasher(hash_size=8, crop_top=0.0, crop_bottom=0.0),
            similarity_threshold=0.92,
        ),
        launcher=launcher,
    )
    session = engine.run()

    assert session.unique_states >= 2
    assert session.actions_performed >= 1
    assert session.stop_reason
    assert session.graph.visited_states
    payload = session.to_dict()
    assert "navigation" in payload
    assert payload["unique_states"] == session.unique_states
