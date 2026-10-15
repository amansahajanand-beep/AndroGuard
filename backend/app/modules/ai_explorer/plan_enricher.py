"""LLM builds / refines a per-app navigation map from trusted static analysis.

Produces an ordered human-like journey (onboard → create → home → sidebar →
settings → ads) using only this APK's activities/SDKs — never domain hardcoding.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.modules.exploration.blueprint import _build_nav_path, _uniq, mine_blueprint
from app.schemas.exploration import (
    AdType,
    ExplorationBlueprint,
    ExplorationGoal,
    GoalKind,
    NavigationStep,
)

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are an Android app exploration planner for AndroGuard.

Given TRUSTED static analysis of ONE uploaded APK, build a navigation MAP that a
careful human tester would follow to exercise core features and surface ads.

You MUST NOT:
- suggest shell, ADB, Python, or credentials
- invent tap coordinates
- invent activities/SDKs not present in the input
- hardcode product domains that are not in THIS app's activity names

You MUST:
- Infer what THIS app is from its activity/class names (whatever domain it is)
- Produce an ORDERED journey like a human:
  1) finish onboarding/permissions if present
  2) perform the core create/add/set-up action for THIS app
  3) return to home / main
  4) open sidebar/drawer/menu and visit each major section
  5) open settings
  6) after core flows, visit actions that show ads (if ad SDKs present)
- Prefer ui_labels derived from THIS app's activity tokens plus generic chrome
  (add, create, save, home, menu, settings, continue, next)

Respond with JSON only:
{
  "app_summary": "one sentence: what this app appears to be",
  "goals": [
    {
      "id": "snake_case_id",
      "kind": "onboarding|create|home|sidebar|settings|destination|feature|ad_trigger",
      "title": "short title",
      "activity_hints": ["ShortActivityName"],
      "ui_labels": ["add","create","save"],
      "expected_ad_types": ["banner"],
      "priority": 50,
      "step_order": 10,
      "why": "brief reason from THIS app's static analysis"
    }
  ],
  "nav_path": [
    {"goal_id": "onboard_...", "order": 0, "summary": "Finish welcome"},
    {"goal_id": "create_...", "order": 1, "summary": "Create core item"},
    {"goal_id": "home", "order": 2, "summary": "Back to home"},
    {"goal_id": "sidebar_menu", "order": 3, "summary": "Open drawer; open each item"},
    {"goal_id": "settings", "order": 4, "summary": "Open settings"}
  ],
  "ad_expectations": ["banner","interstitial"],
  "preferred_labels": ["add","create","home","menu","settings"],
  "ad_trigger_labels": ["watch","reward"],
  "notes": "optional"
}
"""

_VALID_KINDS = {
    "feature",
    "create",
    "settings",
    "onboarding",
    "ad_trigger",
    "destination",
    "sidebar",
    "home",
}


class EnrichedPlanPayload(BaseModel):
    app_summary: str | None = None
    goals: list[ExplorationGoal] = Field(default_factory=list)
    nav_path: list[NavigationStep] = Field(default_factory=list)
    ad_expectations: list[AdType] = Field(default_factory=list)
    preferred_labels: list[str] = Field(default_factory=list)
    ad_trigger_labels: list[str] = Field(default_factory=list)
    notes: str | None = None


def _as_dict(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def compress_static_summary(analysis: Any, *, max_activities: int = 50) -> dict[str, Any]:
    """Trusted compact summary for the enricher (no UI strings)."""
    payload = _as_dict(analysis)
    data = _as_dict(payload.get("data")) or payload
    apk = _as_dict(data.get("apk"))
    manifest = _as_dict(data.get("manifest"))
    package = apk.get("package_name") or manifest.get("package")

    activities: list[dict[str, Any]] = []
    for raw in data.get("activities") or []:
        entry = _as_dict(raw)
        name = entry.get("name")
        if name and entry.get("enabled") is not False:
            short = str(name).rsplit(".", 1)[-1]
            activities.append({"short": short, "full": str(name)})
        if len(activities) >= max_activities:
            break

    code = _as_dict(data.get("code_analysis"))
    sdks = []
    for item in code.get("third_party_sdk_usage") or []:
        entry = _as_dict(item) if not isinstance(item, str) else {"name": item}
        name = entry.get("name")
        if name:
            sdks.append(
                {
                    "name": str(name),
                    "class_count": entry.get("class_count"),
                    "sample_classes": (entry.get("sample_classes") or [])[:3],
                }
            )

    app_classes = []
    for item in code.get("classes") or []:
        entry = _as_dict(item)
        if entry.get("is_app_code") and entry.get("name"):
            app_classes.append(str(entry["name"]).rsplit(".", 1)[-1])
        if len(app_classes) >= 30:
            break

    network = []
    for item in code.get("network_strings") or []:
        entry = _as_dict(item) if not isinstance(item, str) else {"value": item}
        value = entry.get("value") or entry.get("url")
        if value:
            network.append(str(value)[:120])
        if len(network) >= 15:
            break

    return {
        "package_name": package,
        "app_label": manifest.get("app_label"),
        "activities": activities,
        "third_party_sdks": sdks,
        "sample_app_classes": app_classes,
        "network_hosts_or_urls": network,
    }


def build_enricher_user_prompt(
    *,
    summary: dict[str, Any],
    baseline: ExplorationBlueprint,
) -> str:
    import json

    lines = [
        "Build a human-like ordered navigation MAP for THIS uploaded app only.",
        "Use activity short names as page destinations. Include sidebar/drawer exploration.",
        "Core flow first (onboard → create/setup → home), then menu sections, then settings, then ads.",
        "",
        "TRUSTED_STATIC_SUMMARY:",
        json.dumps(summary, ensure_ascii=True)[:9000],
        "",
        "BASELINE_BLUEPRINT (seed — improve into a full ordered map):",
        json.dumps(baseline.model_dump(), ensure_ascii=True)[:7000],
        "",
        "Return JSON only.",
    ]
    return "\n".join(lines)


def _clean_goal(goal: ExplorationGoal) -> ExplorationGoal:
    kind: GoalKind = goal.kind if goal.kind in _VALID_KINDS else "destination"  # type: ignore[assignment]
    return ExplorationGoal(
        id=str(goal.id)[:64],
        kind=kind,
        title=(goal.title or goal.id)[:120],
        activity_hints=[h[:80] for h in (goal.activity_hints or [])[:8]],
        ui_labels=_uniq([str(x).lower()[:40] for x in (goal.ui_labels or [])])[:14],
        expected_ad_types=list(goal.expected_ad_types or [])[:6],
        priority=int(goal.priority or 50),
        step_order=int(goal.step_order if goal.step_order is not None else 50),
        why=(goal.why or "")[:240] or None,
    )


def merge_enriched_plan(
    baseline: ExplorationBlueprint,
    enriched: EnrichedPlanPayload,
) -> ExplorationBlueprint:
    """Prefer LLM map when present; keep baseline SDK expectations."""
    by_id: dict[str, ExplorationGoal] = {}
    # Start from enriched goals when LLM provided a real map; else baseline.
    seed = enriched.goals if enriched.goals else baseline.goals
    for goal in seed:
        cleaned = _clean_goal(goal)
        by_id[cleaned.id] = cleaned

    # Ensure critical chrome goals survive.
    for goal in baseline.goals:
        if goal.kind in {"sidebar", "home", "ad_trigger"} and goal.id not in by_id:
            by_id[goal.id] = goal
        elif goal.id in by_id:
            existing = by_id[goal.id]
            by_id[goal.id] = ExplorationGoal(
                id=existing.id,
                kind=existing.kind,
                title=existing.title or goal.title,
                activity_hints=_uniq(list(existing.activity_hints) + list(goal.activity_hints))[:10],
                ui_labels=_uniq(list(existing.ui_labels) + list(goal.ui_labels))[:16],
                expected_ad_types=list(
                    dict.fromkeys(list(existing.expected_ad_types) + list(goal.expected_ad_types))
                )[:6],
                priority=max(existing.priority, goal.priority),
                step_order=min(existing.step_order, goal.step_order),
                why=existing.why or goal.why,
            )

    goals = list(by_id.values())

    if enriched.nav_path:
        known = {g.id for g in goals}
        nav_path = [
            NavigationStep(
                goal_id=step.goal_id[:64],
                order=int(step.order),
                summary=(step.summary or "")[:160],
            )
            for step in sorted(enriched.nav_path, key=lambda s: s.order)
            if step.goal_id in known
        ]
        # Append any goals missing from LLM path.
        have = {s.goal_id for s in nav_path}
        for g in sorted(goals, key=lambda x: (x.step_order, -x.priority)):
            if g.id not in have:
                nav_path.append(
                    NavigationStep(goal_id=g.id, order=len(nav_path), summary=g.title)
                )
    else:
        nav_path = _build_nav_path(goals)

    # Sync step_order from nav_path.
    order_map = {s.goal_id: s.order for s in nav_path}
    for i, g in enumerate(goals):
        if g.id in order_map:
            goals[i] = ExplorationGoal(
                id=g.id,
                kind=g.kind,
                title=g.title,
                activity_hints=g.activity_hints,
                ui_labels=g.ui_labels,
                expected_ad_types=g.expected_ad_types,
                priority=g.priority,
                step_order=10 + order_map[g.id] * 10,
                why=g.why,
            )

    goals.sort(key=lambda g: (g.step_order, -g.priority, g.id))
    ad_expectations = list(
        dict.fromkeys(list(baseline.ad_expectations) + list(enriched.ad_expectations or []))
    )
    preferred = _uniq(
        list(enriched.preferred_labels or [])
        + list(baseline.preferred_labels)
        + [lab for g in goals for lab in g.ui_labels]
    )
    triggers = _uniq(
        list(enriched.ad_trigger_labels or []) + list(baseline.ad_trigger_labels)
    )
    return ExplorationBlueprint(
        package_name=baseline.package_name,
        app_summary=(enriched.app_summary or baseline.app_summary or "")[:300] or None,
        goals=goals,
        nav_path=nav_path,
        ad_expectations=ad_expectations,  # type: ignore[arg-type]
        ad_sdk_names=list(baseline.ad_sdk_names),
        preferred_labels=preferred,
        ad_trigger_labels=triggers,
        source="llm_nav_map" if enriched.goals else "deterministic+llm",
        enricher_notes=(enriched.notes or "")[:400] or None,
    )


def enrich_blueprint(
    analysis: Any,
    *,
    baseline: ExplorationBlueprint | None = None,
    force: bool = False,
) -> ExplorationBlueprint:
    """Return baseline, optionally refined into a full LLM nav map."""
    base = baseline or mine_blueprint(analysis)
    plan_on = bool(getattr(settings, "ai_exploration_plan_enabled", True))
    ai_on = bool(settings.ai_explorer_enabled)
    has_key = bool((settings.ai_explorer_api_key or "").strip())
    if not force and not (plan_on and ai_on and has_key):
        return base

    summary = compress_static_summary(analysis)
    user = build_enricher_user_prompt(summary=summary, baseline=base)
    try:
        from app.modules.ai_explorer.llm import chat_json

        raw = chat_json(system=PLAN_SYSTEM_PROMPT, user=user)
        payload = EnrichedPlanPayload.model_validate(raw)
        return merge_enriched_plan(base, payload)
    except (ValidationError, Exception) as exc:
        logger.info("Exploration plan enricher fallback to deterministic (%s)", exc)
        return base


def build_exploration_blueprint(analysis: Any) -> ExplorationBlueprint:
    """Mine + optionally enrich — single entry used by prior / pipeline."""
    baseline = mine_blueprint(analysis)
    return enrich_blueprint(analysis, baseline=baseline)
