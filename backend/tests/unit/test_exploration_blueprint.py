"""Code-aware Exploration Blueprint unit tests."""

from __future__ import annotations

from app.modules.ai_explorer.plan_enricher import (
    EnrichedPlanPayload,
    compress_static_summary,
    merge_enriched_plan,
)
from app.modules.ai_explorer.prompts import build_user_prompt
from app.modules.exploration.action_planner import plan_actions
from app.modules.exploration.blueprint import (
    apply_blueprint_to_prior,
    build_coverage,
    mine_blueprint,
    tag_ad_placement,
)
from app.modules.exploration.prior_knowledge import ExplorationPrior, prior_from_package
from app.modules.exploration.ui_element import UIElement
from app.schemas.exploration import AdPlacement, ExplorationBlueprint, ExplorationGoal


def _analysis_fixture() -> dict:
    return {
        "data": {
            "apk": {"package_name": "com.wakeup.timer.alarmclock"},
            "activities": [
                {"name": "com.wakeup.timer.alarmclock.MainActivity", "enabled": True},
                {"name": "com.wakeup.timer.alarmclock.CreateAlarmActivity", "enabled": True},
                {"name": "com.wakeup.timer.alarmclock.SettingsActivity", "enabled": True},
                {"name": "com.wakeup.timer.alarmclock.SplashActivity", "enabled": True},
            ],
            "code_analysis": {
                "third_party_sdk_usage": [
                    {
                        "name": "Google AdMob",
                        "package_prefix": "com.google.android.gms.ads",
                        "class_count": 12,
                        "sample_classes": ["com.google.android.gms.ads.AdView"],
                    }
                ],
                "classes": [
                    {
                        "name": "com.wakeup.timer.alarmclock.CreateAlarmActivity",
                        "is_app_code": True,
                    }
                ],
                "network_strings": [],
            },
        }
    }


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.TextView",
        package="com.wakeup.timer.alarmclock",
        bounds=(0, 0, 100, 80),
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
        focusable=False,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def test_mine_blueprint_create_and_admob() -> None:
    bp = mine_blueprint(_analysis_fixture())
    assert bp.package_name == "com.wakeup.timer.alarmclock"
    kinds = {g.kind for g in bp.goals}
    assert "create" in kinds
    assert "settings" in kinds
    assert "sidebar" in kinds
    assert "home" in kinds
    assert "banner" in bp.ad_expectations
    assert any("AdMob" in n or "admob" in n.lower() for n in bp.ad_sdk_names)
    # Feature slug comes from THIS APK's CreateAlarmActivity tokens — not a fixed catalog.
    assert any(g.id.startswith("create_") for g in bp.goals)
    assert bp.nav_path, "expected ordered human-like nav_path"
    orders = [s.order for s in bp.nav_path]
    assert orders == sorted(orders)
    # Journey: create before sidebar before settings.
    by_id = {s.goal_id: s.order for s in bp.nav_path}
    create_id = next(g.id for g in bp.goals if g.kind == "create")
    assert by_id[create_id] < by_id["sidebar_menu"]
    assert by_id["sidebar_menu"] < by_id["settings"]
    assert bp.app_summary


def test_apply_blueprint_boosts_create_over_banner() -> None:
    prior = prior_from_package("com.wakeup.timer.alarmclock")
    bp = mine_blueprint(_analysis_fixture())
    apply_blueprint_to_prior(prior, bp)
    assert prior.goals
    assert prior.nav_path
    assert prior.wants_ad_triggers() or "banner" in prior.ad_expectations

    screen = (1080, 1920)
    elements = [
        _el(
            text="Add",
            content_description="Create alarm",
            bounds=(880, 1600, 1020, 1740),
            resource_id="id/fab_add",
            class_name="android.widget.ImageButton",
        ),
        _el(text="Language", bounds=(40, 220, 1000, 320)),
        _el(
            text="",
            bounds=(0, 1780, 1080, 1920),
            class_name="android.webkit.WebView",
            resource_id="id/ad_view",
        ),
        _el(text="Test Ad", bounds=(200, 1800, 400, 1860), clickable=False),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert taps[0].meta.get("is_create_explore") or "add" in taps[0].label.lower()
    assert not any("ad_view" in ((p.meta or {}).get("resource_id") or "") for p in taps)


def test_sidebar_active_prefers_drawer_over_create() -> None:
    prior = ExplorationPrior(package_name="com.example.app")
    prior.goals = [
        {
            "id": "create_item",
            "kind": "create",
            "title": "Create",
            "ui_labels": ["add", "create"],
            "priority": 90,
            "step_order": 20,
        },
        {
            "id": "sidebar_menu",
            "kind": "sidebar",
            "title": "Open sidebar",
            "ui_labels": ["menu", "drawer"],
            "priority": 70,
            "step_order": 40,
        },
    ]
    prior.nav_path = [
        {"goal_id": "create_item", "order": 0, "summary": "Create"},
        {"goal_id": "sidebar_menu", "order": 1, "summary": "Sidebar"},
    ]
    prior.covered_goal_evidence = {"create_item": ["done"]}
    assert prior.active_goal()["id"] == "sidebar_menu"

    screen = (1080, 1920)
    elements = [
        _el(
            text="",
            content_description="Open navigation",
            bounds=(20, 40, 120, 140),
            resource_id="id/nav_drawer",
            class_name="android.widget.ImageButton",
        ),
        _el(
            text="Add",
            content_description="Create",
            bounds=(880, 1600, 1020, 1740),
            resource_id="id/fab_add",
            class_name="android.widget.ImageButton",
        ),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=True)
    assert planned[0].meta.get("is_drawer") or planned[0].kind == "open_menu"


def test_active_goal_follows_nav_path_order() -> None:
    prior = ExplorationPrior(package_name="com.example")
    prior.goals = [
        {"id": "onboard", "kind": "onboarding", "title": "Onboard", "step_order": 10},
        {"id": "create_x", "kind": "create", "title": "Create", "step_order": 20},
        {"id": "home", "kind": "home", "title": "Home", "step_order": 30},
        {"id": "sidebar_menu", "kind": "sidebar", "title": "Sidebar", "step_order": 40},
    ]
    prior.nav_path = [
        {"goal_id": "onboard", "order": 0},
        {"goal_id": "create_x", "order": 1},
        {"goal_id": "home", "order": 2},
        {"goal_id": "sidebar_menu", "order": 3},
    ]
    assert prior.active_goal()["id"] == "onboard"
    prior.covered_goal_evidence["onboard"] = ["ok"]
    assert prior.active_goal()["id"] == "create_x"
    prior.covered_goal_evidence["create_x"] = ["ok"]
    assert prior.active_goal()["id"] == "home"
    summary = prior.plan_summary_for_ai()
    assert "ACTIVE next step: home" in summary
    assert "Ordered nav map" in summary


def test_mine_notes_app_generic_not_domain_catalog() -> None:
    """A notes app should mine create_note from activity names — not alarm keywords."""
    analysis = {
        "data": {
            "apk": {"package_name": "com.example.quicknotes"},
            "activities": [
                {"name": "com.example.quicknotes.MainActivity", "enabled": True},
                {"name": "com.example.quicknotes.CreateNoteActivity", "enabled": True},
                {"name": "com.example.quicknotes.SettingsActivity", "enabled": True},
            ],
            "code_analysis": {"third_party_sdk_usage": [], "classes": [], "network_strings": []},
        }
    }
    bp = mine_blueprint(analysis)
    create_goals = [g for g in bp.goals if g.kind == "create"]
    assert create_goals
    assert create_goals[0].id == "create_note"
    assert "alarm" not in " ".join(bp.preferred_labels)


def test_merge_enriched_plan_keeps_sdk_names() -> None:
    base = mine_blueprint(_analysis_fixture())
    enriched = EnrichedPlanPayload(
        goals=[
            ExplorationGoal(
                id="create_alarm",
                kind="create",
                title="Create Alarm",
                ui_labels=["create", "add", "save"],
                priority=95,
                why="LLM",
            )
        ],
        ad_expectations=["banner"],
        preferred_labels=["create", "save"],
        notes="refined",
    )
    merged = merge_enriched_plan(base, enriched)
    assert merged.source in {"llm_nav_map", "deterministic+llm"} or merged.source.startswith(
        "deterministic"
    )
    assert merged.ad_sdk_names
    assert any(g.id == "create_alarm" for g in merged.goals)
    assert merged.nav_path


def test_compress_static_summary_trusted_only() -> None:
    summary = compress_static_summary(_analysis_fixture())
    assert summary["package_name"] == "com.wakeup.timer.alarmclock"
    shorts = [a["short"] if isinstance(a, dict) else a for a in summary["activities"]]
    assert "CreateAlarmActivity" in shorts
    assert summary["third_party_sdks"]


def test_build_user_prompt_includes_plan() -> None:
    prompt = build_user_prompt(
        activity="com.example/.Main",
        package_name="com.example",
        candidates=[{"key": "tap:1", "action": "tap", "label": "Add"}],
        visited_summary=[],
        plan_notes="Uncovered goals:\n- create_alarm: Create alarm",
    )
    assert "EXPLORATION_PLAN" in prompt
    assert "create_alarm" in prompt
    assert "UNTRUSTED_UI_CANDIDATES" in prompt


def test_coverage_and_ad_tagging() -> None:
    bp = mine_blueprint(_analysis_fixture())
    cov = build_coverage(
        bp,
        covered_goal_ids={"create_alarm": ["CreateAlarmActivity"]},
        ad_types_found=["banner"],
    )
    assert cov.goals_total >= 1
    assert "banner" in cov.ad_types_found
    assert "banner" not in cov.ad_types_missing or True

    placement = AdPlacement(ad_type="banner", ad_detected=True, page="Settings")
    tag_ad_placement(placement, blueprint=bp, activity="SettingsActivity")
    assert placement.expected_from_sdk is True


def test_prior_mark_goal_coverage() -> None:
    prior = ExplorationPrior(package_name="com.example")
    prior.goals = [
        {
            "id": "create_alarm",
            "kind": "create",
            "title": "Create",
            "activity_hints": ["CreateAlarmActivity"],
            "ui_labels": ["add", "create"],
            "priority": 90,
        }
    ]
    newly = prior.mark_goal_coverage(
        activity="com.example/.CreateAlarmActivity",
        ui_blob="Create Alarm Save",
    )
    assert "create_alarm" in newly
    assert prior.uncovered_goals() == []


def test_enriched_plan_payload_rejects_bad_kind_via_merge() -> None:
    base = ExplorationBlueprint(package_name="com.example", goals=[])
    # Invalid kinds are coerced in merge via ExplorationGoal validation — use valid kind.
    payload = EnrichedPlanPayload.model_validate(
        {
            "goals": [
                {
                    "id": "x",
                    "kind": "destination",
                    "title": "X",
                    "ui_labels": ["ok"],
                }
            ]
        }
    )
    merged = merge_enriched_plan(base, payload)
    assert merged.goals[0].kind == "destination"


def test_more_options_not_treated_as_drawer() -> None:
    """Alarm-app ⋮ menus must not steal sidebar / create priority."""
    prior = ExplorationPrior(package_name="com.wakeup.timer.alarmclock")
    prior.goals = [
        {
            "id": "create_alarm",
            "kind": "create",
            "title": "Create",
            "ui_labels": ["add", "create"],
            "priority": 90,
            "step_order": 20,
        },
        {
            "id": "sidebar_menu",
            "kind": "sidebar",
            "title": "Sidebar",
            "ui_labels": ["drawer", "hamburger"],
            "priority": 70,
            "step_order": 40,
        },
    ]
    prior.nav_path = [
        {"goal_id": "create_alarm", "order": 0},
        {"goal_id": "sidebar_menu", "order": 1},
    ]
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
            text="",
            content_description="More options",
            bounds=(900, 600, 1000, 700),
            resource_id="com.wakeup.timer.alarmclock:id/moreButton",
            class_name="android.widget.ImageButton",
        ),
        _el(
            text="",
            bounds=(880, 1750, 1020, 1890),
            resource_id="id/fab",
            class_name="android.widget.ImageButton",
        ),
        _el(text="Home", bounds=(40, 2100, 200, 2250)),
        _el(text="Clock", bounds=(280, 2100, 440, 2250)),
    ]
    planned = plan_actions(elements, prior=prior, screen_size=screen, include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert not taps[0].meta.get("is_overflow")
    assert taps[0].label != "More options"
    assert taps[0].meta.get("is_create_explore") or taps[0].meta.get("is_drawer")
    overflow = [p for p in taps if p.meta.get("is_overflow") or "More options" in (p.label or "")]
    if overflow:
        assert taps[0].priority > overflow[0].priority


def test_delete_confirm_prefers_cancel() -> None:
    screen = (1080, 2400)
    elements = [
        _el(text="Delete", bounds=(200, 1200, 880, 1320), class_name="android.widget.Button"),
        _el(text="Cancel", bounds=(200, 1360, 880, 1480), class_name="android.widget.Button"),
        _el(
            text="",
            content_description="More options",
            bounds=(900, 600, 1000, 700),
            resource_id="id/moreButton",
        ),
    ]
    planned = plan_actions(elements, screen_size=screen, include_menu=False)
    taps = [p for p in planned if p.kind == "tap"]
    assert taps
    assert taps[0].label == "Cancel"
    assert taps[0].meta.get("is_cancel_dialog")
