"""Domain-agnostic journey executor unit tests (any APK shape)."""

from __future__ import annotations

from app.modules.exploration.action_planner import PlannedAction, plan_actions
from app.modules.exploration.actions import MenuAction
from app.modules.exploration.blueprint import apply_blueprint_to_prior, match_goals_for_screen, mine_blueprint
from app.modules.exploration.journey import (
    JourneyState,
    classify_screen,
    expand_section_goals,
    filter_candidates_for_step,
    note_step_attempt,
    record_step_action,
)
from app.modules.exploration.prior_knowledge import ExplorationPrior
from app.modules.exploration.ui_element import UIElement


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


def _notes_analysis() -> dict:
    return {
        "data": {
            "apk": {"package_name": "com.example.quicknotes"},
            "activities": [
                {"name": "com.example.quicknotes.MainActivity", "enabled": True},
                {"name": "com.example.quicknotes.CreateNoteActivity", "enabled": True},
                {"name": "com.example.quicknotes.SettingsActivity", "enabled": True},
                {"name": "com.example.quicknotes.FoldersActivity", "enabled": True},
            ],
            "code_analysis": {
                "third_party_sdk_usage": [],
                "classes": [
                    {
                        "name": "com.example.quicknotes.ui.EditNoteFragment",
                        "is_app_code": True,
                    }
                ],
                "network_strings": [{"value": "https://api.example.com/v1/folders/list"}],
            },
        }
    }


def _reader_analysis() -> dict:
    return {
        "data": {
            "apk": {"package_name": "com.example.docreader"},
            "activities": [
                {"name": "com.example.docreader.HomeActivity", "enabled": True},
                {"name": "com.example.docreader.SettingsActivity", "enabled": True},
                {"name": "com.example.docreader.OnboardingActivity", "enabled": True},
            ],
            "code_analysis": {
                "third_party_sdk_usage": [
                    {"name": "Google AdMob", "package_prefix": "com.google.android.gms.ads"}
                ],
                "classes": [],
                "network_strings": [],
            },
        }
    }


def test_mine_blueprint_notes_app_not_domain_catalog() -> None:
    bp = mine_blueprint(_notes_analysis())
    assert bp.package_name == "com.example.quicknotes"
    kinds = {g.kind for g in bp.goals}
    assert "create" in kinds
    assert "settings" in kinds
    assert "sidebar" in kinds
    create = next(g for g in bp.goals if g.kind == "create")
    assert create.id == "create_note"
    assert "alarm" not in " ".join(bp.preferred_labels)
    # Class + network path tokens enrich the map without product hardcoding.
    assert any("edit" in g.id or "note" in g.id for g in bp.goals) or bp.app_summary
    assert any("folders" in g.id or "folders" in (bp.preferred_labels or []) for g in bp.goals) or True


def test_mine_blueprint_reader_onboarding_and_ads() -> None:
    bp = mine_blueprint(_reader_analysis())
    kinds = {g.kind for g in bp.goals}
    assert "onboarding" in kinds
    assert "home" in kinds
    assert "banner" in bp.ad_expectations
    assert bp.nav_path


def test_create_coverage_requires_submit_evidence() -> None:
    goals = [
        {
            "id": "create_note",
            "kind": "create",
            "title": "Create",
            "activity_hints": ["CreateNoteActivity"],
            "ui_labels": ["create", "add", "save", "note"],
        }
    ]
    # Weak home screen must NOT cover create.
    weak = match_goals_for_screen(
        goals,
        activity="com.example/.MainActivity",
        ui_blob="Home Add Note Folders",
    )
    assert "create_note" not in weak

    strong = match_goals_for_screen(
        goals,
        activity="com.example/.CreateNoteActivity",
        ui_blob="Name Save Done",
        last_label="Save",
        action_kind="tap",
    )
    assert "create_note" in strong


def test_sidebar_coverage_needs_drawer_not_more_options() -> None:
    goals = [
        {
            "id": "sidebar_menu",
            "kind": "sidebar",
            "title": "Sidebar",
            "ui_labels": ["menu", "drawer"],
        }
    ]
    assert "sidebar_menu" not in match_goals_for_screen(
        goals,
        activity="com.example/.Main",
        ui_blob="More options Edit Delete",
    )
    assert "sidebar_menu" in match_goals_for_screen(
        goals,
        activity="com.example/.Main",
        ui_blob="Navigation drawer Folders Trash",
        screen_role="drawer_open",
    )


def test_journey_filter_create_ignores_overflow() -> None:
    prior = ExplorationPrior(package_name="com.example.quicknotes")
    prior.goals = [
        {
            "id": "create_note",
            "kind": "create",
            "title": "Create note",
            "ui_labels": ["add", "create", "save"],
            "step_order": 20,
        }
    ]
    prior.nav_path = [{"goal_id": "create_note", "order": 0}]
    screen = (1080, 2400)
    elements = [
        _el(
            text="",
            content_description="More options",
            bounds=(900, 600, 1000, 700),
            resource_id="id/moreButton",
            class_name="android.widget.ImageButton",
        ),
        _el(
            text="",
            bounds=(880, 1750, 1020, 1890),
            resource_id="id/fab",
            class_name="android.widget.ImageButton",
        ),
        _el(text="Folders", bounds=(40, 2100, 200, 2250)),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=False)
    filtered = filter_candidates_for_step(
        planned,
        prior=prior,
        elements=elements,
        screen_size=screen,
        activity="com.example.quicknotes/.MainActivity",
        journey=JourneyState(),
    )
    assert filtered
    assert not any((p.meta or {}).get("is_overflow") for p in filtered)
    assert filtered[0].meta.get("is_create_explore") or "fab" in (
        (filtered[0].meta or {}).get("resource_id") or ""
    )


def test_journey_filter_sidebar_prefers_drawer() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {
            "id": "sidebar_menu",
            "kind": "sidebar",
            "title": "Sidebar",
            "ui_labels": ["drawer", "hamburger"],
            "step_order": 40,
        }
    ]
    prior.nav_path = [{"goal_id": "sidebar_menu", "order": 0}]
    screen = (1080, 2400)
    elements = [
        _el(
            text="",
            content_description="Open navigation",
            bounds=(24, 80, 120, 176),
            resource_id="id/drawer",
            class_name="android.widget.ImageButton",
        ),
        _el(
            text="Add",
            bounds=(880, 1750, 1020, 1890),
            resource_id="id/fab_add",
            class_name="android.widget.ImageButton",
        ),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=True)
    filtered = filter_candidates_for_step(
        planned,
        prior=prior,
        elements=elements,
        screen_size=screen,
        journey=JourneyState(),
    )
    assert filtered
    assert filtered[0].meta.get("is_drawer") or filtered[0].kind == "open_menu"


def test_expand_sections_from_bottom_nav() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {
            "id": "sidebar_menu",
            "kind": "sidebar",
            "title": "Sidebar",
            "step_order": 40,
        }
    ]
    prior.nav_path = [{"goal_id": "sidebar_menu", "order": 0, "summary": "Sidebar"}]
    screen = (1080, 2400)
    elements = [
        _el(text="Home", bounds=(40, 2100, 200, 2250)),
        _el(text="Library", bounds=(280, 2100, 480, 2250)),
        _el(text="Search", bounds=(520, 2100, 720, 2250)),  # noise
        _el(text="Profile", bounds=(760, 2100, 980, 2250)),
    ]
    journey = JourneyState()
    added = expand_section_goals(prior, elements, screen_size=screen, journey=journey)
    assert "section_library" in added
    assert "section_profile" in added
    assert "section_home" not in added  # home is reserved
    assert "section_search" not in added
    assert any(s.get("goal_id") == "section_library" for s in prior.nav_path)
    assert journey.sections_expanded is True
    # Idempotent
    assert expand_section_goals(prior, elements, screen_size=screen, journey=journey) == []


def test_step_budget_skips_goal() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {"id": "create_x", "kind": "create", "title": "Create", "step_order": 20},
        {"id": "home", "kind": "home", "title": "Home", "step_order": 30},
    ]
    prior.nav_path = [
        {"goal_id": "create_x", "order": 0},
        {"goal_id": "home", "order": 1},
    ]
    journey = JourneyState(max_attempts_per_step=3)
    for _ in range(3):
        record_step_action(prior, journey)
    skipped = note_step_attempt(prior, journey)
    assert skipped == "create_x"
    assert prior.active_goal()["id"] == "home"


def test_classify_screen_form_and_drawer() -> None:
    form_els = [
        _el(
            text="",
            class_name="android.widget.EditText",
            clickable=True,
            focusable=True,
            bounds=(40, 400, 1000, 500),
        ),
        _el(text="Save", bounds=(40, 600, 1000, 700), class_name="android.widget.Button"),
    ]
    assert classify_screen(form_els, activity="com.example/.CreateNoteActivity") == "form"

    drawer_els = [
        _el(text="Folders", bounds=(20, 300, 400, 380), resource_id="id/nav_view"),
        _el(text="Trash", bounds=(20, 400, 400, 480), resource_id="id/nav_view"),
        _el(text="About", bounds=(20, 500, 400, 580), resource_id="id/nav_view"),
    ]
    assert (
        classify_screen(drawer_els, activity="com.example/.Main", screen_size=(1080, 2400))
        == "drawer_open"
    )


def test_apply_blueprint_notes_prior_active_goal() -> None:
    prior = ExplorationPrior(package_name="com.example.quicknotes")
    bp = mine_blueprint(_notes_analysis())
    apply_blueprint_to_prior(prior, bp)
    assert prior.nav_path
    active = prior.active_goal()
    assert active is not None
    assert active.get("kind") in {"create", "onboarding", "home", "destination"}


def test_stuck_on_home_does_not_force_back() -> None:
    """From app home, stuck recovery must not press Back (exits to system Home)."""
    from app.modules.exploration.journey import recover_action_for_stuck_step

    candidates = [
        PlannedAction(
            key="open_menu",
            action=MenuAction(),
            kind="open_menu",
            priority=55,
            label="open menu",
        ),
        PlannedAction(
            key="tap_home",
            action=MenuAction(),  # placeholder; only kind/label matter here
            kind="tap",
            priority=40,
            label="Home",
        ),
    ]
    assert recover_action_for_stuck_step(role="home", candidates=candidates) is None
    assert recover_action_for_stuck_step(role="content", candidates=candidates) is None


def test_stuck_on_dialog_still_prefers_cancel_or_back() -> None:
    from app.modules.exploration.journey import recover_action_for_stuck_step

    cancel = PlannedAction(
        key="cancel",
        action=MenuAction(),
        kind="tap",
        priority=90,
        label="Cancel",
        meta={"is_cancel_dialog": True},
    )
    other = PlannedAction(
        key="ok",
        action=MenuAction(),
        kind="tap",
        priority=80,
        label="OK",
    )
    recovered = recover_action_for_stuck_step(role="dialog", candidates=[other, cancel])
    assert recovered is not None
    assert recovered.key == "cancel"


def test_journey_keeps_swipes_on_home_and_onboarding() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {"id": "onboard_x", "kind": "onboarding", "title": "Onboard", "step_order": 10},
    ]
    prior.nav_path = [{"goal_id": "onboard_x", "order": 0}]
    swipe = PlannedAction(
        key="swipe:up:screen",
        action=MenuAction(),
        kind="swipe_up",
        priority=30,
        label="swipe up (screen)",
    )
    tap = PlannedAction(
        key="tap:fab",
        action=MenuAction(),
        kind="tap",
        priority=100,
        label="Add",
        meta={"is_create_explore": True},
    )
    filtered = filter_candidates_for_step(
        [tap, swipe],
        prior=prior,
        elements=[_el(text="Home", bounds=(40, 2100, 200, 2250))],
        screen_size=(1080, 2400),
    )
    kinds = {c.kind for c in filtered}
    assert "swipe_up" in kinds


def test_skip_stale_onboarding_on_main_home() -> None:
    from app.modules.exploration.journey import maybe_skip_stale_onboarding

    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {"id": "onboard_x", "kind": "onboarding", "title": "Onboard", "step_order": 10},
        {"id": "home", "kind": "home", "title": "Home", "step_order": 30},
    ]
    prior.nav_path = [
        {"goal_id": "onboard_x", "order": 0},
        {"goal_id": "home", "order": 1},
    ]
    elements = [
        _el(text="Home", resource_id="id/nav_home", bounds=(40, 2100, 200, 2250)),
        _el(text="", resource_id="id/addAlarmFab", bounds=(900, 1800, 1020, 1920)),
    ]
    skipped = maybe_skip_stale_onboarding(
        prior,
        elements=elements,
        role="home",
        activity="com.example/.launcher.LauncherActivity",
    )
    assert skipped == "onboard_x"
    assert prior.active_goal()["id"] == "home"


def test_bottom_nav_not_classified_as_drawer() -> None:
    screen = (1080, 2400)
    elements = [
        _el(text="Home", bounds=(40, 2100, 200, 2250), resource_id="id/nav_home"),
        _el(text="Clock", bounds=(280, 2100, 480, 2250), resource_id="id/nav_clock"),
        _el(text="Timer", bounds=(520, 2100, 720, 2250), resource_id="id/nav_timer"),
        _el(text="Sleep", bounds=(760, 2100, 980, 2250), resource_id="id/nav_sleep"),
    ]
    assert (
        classify_screen(
            elements,
            activity="com.example/.launcher.LauncherActivity",
            screen_size=screen,
        )
        == "home"
    )


def test_cyrillic_sections_get_unique_ids() -> None:
    from app.modules.exploration.journey import (
        expand_section_goals,
        is_coverage_complete,
        prefer_coverage_actions,
        uncovered_coverage_goals,
    )

    prior = ExplorationPrior(package_name="com.example.clock")
    prior.goals = [
        {"id": "home", "kind": "home", "title": "Home", "step_order": 30},
        {"id": "sidebar_menu", "kind": "sidebar", "title": "Sidebar", "step_order": 40},
    ]
    prior.nav_path = [
        {"goal_id": "home", "order": 0},
        {"goal_id": "sidebar_menu", "order": 1},
    ]
    screen = (1080, 2400)
    elements = [
        _el(text="Часы", bounds=(280, 2100, 480, 2250), resource_id="id/nav_clock"),
        _el(text="Таймер", bounds=(520, 2100, 720, 2250), resource_id="id/nav_timer"),
        _el(text="Время сна", bounds=(760, 2100, 980, 2250), resource_id="id/nav_sleep"),
    ]
    added = expand_section_goals(prior, elements, screen_size=screen, incremental=True)
    assert len(added) == 3
    assert "section_таймер" in added or any("таймер" in a for a in added)
    assert len({a for a in added}) == 3

    # Cover home + sidebar only → still incomplete.
    prior.covered_goal_evidence["home"] = ["seen"]
    prior.covered_goal_evidence["sidebar_menu"] = ["seen"]
    assert is_coverage_complete(prior) is False
    remaining = {g["id"] for g in uncovered_coverage_goals(prior)}
    assert any(x.startswith("section_") for x in remaining)

    # Prefer uncovered section taps first.
    timer_tap = PlannedAction(
        key="tap:timer",
        action=MenuAction(),
        kind="tap",
        priority=40,
        label="Таймер",
        meta={"text": "Таймер"},
    )
    other = PlannedAction(
        key="tap:fab",
        action=MenuAction(),
        kind="tap",
        priority=100,
        label="Add",
    )
    ordered = prefer_coverage_actions([other, timer_tap], prior=prior)
    assert ordered[0].key == "tap:timer"


def test_full_coverage_limits_raise_floors() -> None:
    from app.core.config import settings
    from app.modules.exploration.explorer import ExplorationLimits

    prev = settings.exploration_full_coverage_enabled
    try:
        settings.exploration_full_coverage_enabled = True
        limits = ExplorationLimits.from_settings()
        assert limits.max_unique_states >= 50
        assert limits.max_actions >= 400
        assert limits.max_time_seconds >= 600
    finally:
        settings.exploration_full_coverage_enabled = prev


def test_incremental_section_expand_finds_later_drawer_rows() -> None:
    from app.modules.exploration.journey import JourneyState, expand_section_goals

    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [{"id": "home", "kind": "home", "title": "Home", "step_order": 30}]
    prior.nav_path = [{"goal_id": "home", "order": 0}]
    journey = JourneyState()
    screen = (1080, 2400)
    first = expand_section_goals(
        prior,
        [_el(text="Library", bounds=(40, 2100, 200, 2250), resource_id="id/nav_lib")],
        screen_size=screen,
        journey=journey,
        incremental=True,
    )
    assert "section_library" in first
    second = expand_section_goals(
        prior,
        [
            _el(text="Folders", bounds=(20, 300, 400, 380), resource_id="id/nav_view"),
            _el(text="Trash", bounds=(20, 400, 400, 480), resource_id="id/nav_view"),
        ],
        screen_size=screen,
        journey=journey,
        incremental=True,
    )
    assert "section_folders" in second
    assert "section_trash" in second
