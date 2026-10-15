"""Phase 12F — APK Intelligence unit + integration tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.context import build_planning_context
from app.modules.ai_explorer.prompts import build_user_prompt
from app.modules.apk_intelligence import (
    ApplicationIntelligence,
    build_application_intelligence,
)
from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import ActionResult, TapAction
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ActionExecutor
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.ui_element import UIElement


def _sample_analysis(**overrides):
    data = {
        "apk": {
            "package_name": "com.example.game",
            "version_name": "1.2.3",
            "version_code": 12,
        },
        "manifest": {"package": "com.example.game", "app_label": "Example Game"},
        "sdk": {"min_sdk": 24, "target_sdk": 34},
        "permissions": [
            {"name": "android.permission.CAMERA", "protection_level": "dangerous"},
            {"name": "android.permission.INTERNET", "protection_level": "normal"},
            {"name": "com.android.vending.BILLING", "protection_level": "normal"},
        ],
        "activities": [
            {
                "name": "com.example.game.MainActivity",
                "exported": True,
                "enabled": True,
                "intent_filters": [
                    {
                        "actions": ["android.intent.action.MAIN"],
                        "categories": ["android.intent.category.LAUNCHER"],
                        "data": [],
                    }
                ],
            },
            {
                "name": "com.example.game.GameActivity",
                "exported": False,
                "enabled": True,
                "intent_filters": [],
            },
            {
                "name": "com.example.game.RewardActivity",
                "exported": False,
                "enabled": True,
                "intent_filters": [],
            },
            {
                "name": "com.example.game.LoginActivity",
                "exported": False,
                "enabled": True,
                "intent_filters": [],
            },
            {
                "name": "com.example.game.SettingsActivity",
                "exported": False,
                "enabled": True,
                "intent_filters": [],
            },
            {
                "name": "com.example.game.DeepLinkActivity",
                "exported": True,
                "enabled": True,
                "intent_filters": [
                    {
                        "actions": ["android.intent.action.VIEW"],
                        "categories": ["android.intent.category.DEFAULT"],
                        "data": [
                            {
                                "scheme": "myapp",
                                "host": "home",
                                "path": None,
                                "path_prefix": None,
                                "path_pattern": None,
                                "mime_type": None,
                                "port": None,
                            }
                        ],
                    }
                ],
            },
        ],
        "services": [{"name": "com.example.game.SyncService"}],
        "code_analysis": {
            "third_party_sdk_usage": [
                {"name": "Google AdMob", "package": "com.google.android.gms.ads"},
                {"name": "Firebase", "package": "com.google.firebase"},
                {"name": "OkHttp", "package": "okhttp3"},
            ],
            "webview_usage": [
                {"label": "WebView.loadUrl", "class": "android.webkit.WebView"}
            ],
            "classes": [
                {"name": "com.google.android.gms.ads.rewarded.RewardedAd", "is_app_code": False},
                {"name": "com.google.android.gms.ads.interstitial.InterstitialAd", "is_app_code": False},
                {"name": "com.example.game.GameActivity", "is_app_code": True},
            ],
            "methods": [
                {
                    "name": "showRewarded",
                    "class": "com.example.game.RewardActivity",
                },
                {
                    "name": "loadInterstitial",
                    "class": "com.example.game.GameActivity",
                },
            ],
        },
    }
    data.update(overrides)
    return {"data": data}


def test_build_intelligence_from_static_analysis() -> None:
    intel = build_application_intelligence(_sample_analysis())
    assert isinstance(intel, ApplicationIntelligence)
    assert intel.status in {"ready", "partial"}
    assert intel.application["package_name"] == "com.example.game"
    assert intel.components["activity_count"] == 6
    assert intel.components["service_count"] == 1
    payload = intel.to_dict()
    json.dumps(payload)


def test_launcher_and_deep_links() -> None:
    intel = build_application_intelligence(_sample_analysis())
    assert "com.example.game.MainActivity" in intel.entry_points["launcher_activities"]
    assert any(a.launcher for a in intel.activities)
    assert any(a.kind == "AUTHENTICATION" for a in intel.activities)
    assert any(a.kind == "SETTINGS" for a in intel.activities)
    assert len(intel.deep_links) >= 1
    assert intel.deep_links[0].scheme == "myapp"


def test_webview_detection() -> None:
    intel = build_application_intelligence(_sample_analysis())
    assert intel.ui_signals["webview_present"] is True


def test_ad_sdk_detection() -> None:
    intel = build_application_intelligence(_sample_analysis())
    names = [s["name"] for s in intel.ads["sdk_candidates"]]
    assert any("Google" in n for n in names)
    for s in intel.ads["sdk_candidates"]:
        assert 0.0 <= s["confidence"] <= 1.0
        assert s["evidence"]


def test_ad_format_detection() -> None:
    intel = build_application_intelligence(_sample_analysis())
    formats = {f["format"] for f in intel.ads["ad_formats"]}
    assert "REWARDED" in formats
    assert "INTERSTITIAL" in formats
    for f in intel.ads["ad_formats"]:
        assert f["kind"] in {"STATIC_SIGNAL", "POSSIBLE_FORMAT", "LIKELY_FORMAT"}
        assert 0.0 <= f["confidence"] <= 1.0


def test_feature_inference_camera() -> None:
    intel = build_application_intelligence(_sample_analysis())
    feats = {f.feature for f in intel.features}
    assert "CAMERA" in feats
    assert "ADS" in feats
    assert "REWARDED_CONTENT" in feats
    assert "WEB_CONTENT" in feats
    assert "IN_APP_PURCHASE" in feats


def test_empty_analysis_does_not_crash() -> None:
    intel = build_application_intelligence({})
    assert intel.status in {"empty", "partial", "ready"}
    json.dumps(intel.to_dict())


def test_partial_code_analysis() -> None:
    analysis = _sample_analysis()
    analysis["data"]["code_analysis"] = {}
    intel = build_application_intelligence(analysis)
    assert intel.application["package_name"] == "com.example.game"
    assert intel.ads["ad_analysis_status"] in {"EMPTY", "PARTIAL", "READY"}


def test_ai_summary_compact() -> None:
    intel = build_application_intelligence(_sample_analysis())
    summary = intel.to_ai_summary()
    assert summary["package"] == "com.example.game"
    assert "ad_sdk_signals" in summary
    assert summary["note"].startswith("STATIC")
    # Must not dump full class lists into AI summary.
    assert "ad_related_classes" not in summary
    json.dumps(summary)


def test_agent_state_attaches_intelligence() -> None:
    intel = build_application_intelligence(_sample_analysis())
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=True,
        application_intelligence=intel,
    )
    assert agent.application_intelligence is intel
    payload = agent.to_dict()
    assert payload["application_intelligence"]["package"] == "com.example.game"


def test_planning_context_includes_apk_intelligence() -> None:
    intel = build_application_intelligence(_sample_analysis())
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=True,
        application_intelligence=intel,
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="GameActivity",
        elements=[
            UIElement(
                text="Get 100 Coins",
                resource_id="",
                content_description="",
                class_name="android.widget.Button",
                package="com.example.game",
                bounds=(0, 0, 100, 80),
                clickable=True,
                enabled=True,
                scrollable=False,
                visible=True,
                selected=False,
                checked=False,
                focused=False,
                focusable=True,
            )
        ],
        state_id="game",
        screen_size=(1080, 2400),
    )
    agent.update_observation(obs)
    ctx = build_planning_context(agent_state=agent, observation=obs)
    assert ctx.application_intelligence is not None
    assert "REWARDED" in {
        f.get("format") for f in (ctx.application_intelligence.get("ad_format_signals") or [])
    }
    prompt = build_user_prompt(
        activity="GameActivity",
        package_name="com.example.game",
        candidates=[{"key": "tap:coins", "action": "tap", "label": "Get 100 Coins"}],
        visited_summary=[],
        planning_context=ctx.to_dict(),
    )
    assert "APPLICATION_INTELLIGENCE" in prompt
    assert "STATIC" in prompt


def test_intelligence_cannot_create_actions() -> None:
    intel = build_application_intelligence(_sample_analysis())
    # Triggers are hypotheses only — no Action / PlannedAction fields.
    for t in intel.ads.get("ad_triggers") or []:
        assert "adb" not in json.dumps(t).lower()
        assert "shell" not in json.dumps(t).lower()
    assert not hasattr(intel, "execute")
    assert not hasattr(intel, "perform")


def test_intelligence_unavailable_planner_still_works() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    assert agent.application_intelligence is None
    cands = [
        PlannedAction(
            key="tap:A",
            action=TapAction(
                element=UIElement(
                    text="A",
                    resource_id="",
                    content_description="",
                    class_name="android.widget.Button",
                    package="com.example.app",
                    bounds=(0, 0, 10, 10),
                    clickable=True,
                    enabled=True,
                    scrollable=False,
                    visible=True,
                    selected=False,
                    checked=False,
                    focused=False,
                    focusable=True,
                )
            ),
            kind="tap",
            label="A",
        )
    ]
    advisor = ExplorationAdvisor(enabled=False)
    planned, meta = advisor.choose(cands)
    assert planned is None
    assert meta["ai_used"] is False
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    result = ActionExecutor(ui).execute(cands[0], agent_state=agent)
    assert result.success is True


def test_integration_static_to_ai_to_executor() -> None:
    intel = build_application_intelligence(_sample_analysis())
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=True,
        application_intelligence=intel,
    )
    # Prefer AD_DISCOVERY goal when present.
    agent.add_goal(
        "discover_ad_placements",
        "Discover ad placements when available",
        goal_type="AD_DISCOVERY",
        priority=1,
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="GameActivity",
        elements=[
            UIElement(
                text="Get 100 Coins",
                resource_id="btn_reward",
                content_description="",
                class_name="android.widget.Button",
                package="com.example.game",
                bounds=(40, 400, 500, 500),
                clickable=True,
                enabled=True,
                scrollable=False,
                visible=True,
                selected=False,
                checked=False,
                focused=False,
                focusable=True,
            ),
            UIElement(
                text="Settings",
                resource_id="btn_settings",
                content_description="",
                class_name="android.widget.Button",
                package="com.example.game",
                bounds=(40, 600, 300, 700),
                clickable=True,
                enabled=True,
                scrollable=False,
                visible=True,
                selected=False,
                checked=False,
                focused=False,
                focusable=True,
            ),
        ],
        state_id="game",
        screen_size=(1080, 2400),
    )
    agent.update_observation(obs)
    ctx = build_planning_context(agent_state=agent, observation=obs)
    assert ctx.application_intelligence is not None

    coins = PlannedAction(
        key="tap:coins",
        action=TapAction(element=obs.clickable_elements and UIElement(
            text="Get 100 Coins",
            resource_id="btn_reward",
            content_description="",
            class_name="android.widget.Button",
            package="com.example.game",
            bounds=(40, 400, 500, 500),
            clickable=True,
            enabled=True,
            scrollable=False,
            visible=True,
            selected=False,
            checked=False,
            focused=False,
            focusable=True,
        )),
        kind="tap",
        label="Get 100 Coins",
    )
    settings = PlannedAction(
        key="tap:settings",
        action=TapAction(
            element=UIElement(
                text="Settings",
                resource_id="btn_settings",
                content_description="",
                class_name="android.widget.Button",
                package="com.example.game",
                bounds=(40, 600, 300, 700),
                clickable=True,
                enabled=True,
                scrollable=False,
                visible=True,
                selected=False,
                checked=False,
                focused=False,
                focusable=True,
            )
        ),
        kind="tap",
        label="Settings",
    )
    advisor = ExplorationAdvisor(enabled=True, min_confidence=0.5)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value={
                "action": "tap",
                "target": "tap:coins",
                "confidence": 0.9,
                "reason": "Rewarded static signal + Get 100 Coins label",
            },
        ):
            planned, meta = advisor.choose(
                [coins, settings],
                force=True,
                planning_context=ctx,
            )
    assert planned is not None
    assert planned.key == "tap:coins"
    assert meta["ai_used"] is True
    # Still only candidate-bound — cannot invent showRewarded()
    assert planned.kind == "tap"
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    assert ActionExecutor(ui).execute(planned, agent_state=agent).success is True


def test_ad_trigger_hypothesis_present() -> None:
    intel = build_application_intelligence(_sample_analysis())
    assert intel.ad_trigger_hypotheses
    hyp = intel.ad_trigger_hypotheses[0].to_dict()
    assert "ad_format" in hyp
    assert 0.0 <= hyp["confidence"] <= 1.0
