"""Deterministic Exploration Blueprint mined from static APK analysis.

Builds a *per-upload* navigation map from activity/SDK names — no hardcoded
app domains (alarm/timer/etc.). Feature tokens come from *this* APK's
activity short names. Optional LLM enricher turns the map into a human-like
ordered journey (onboard → create → home → sidebar → settings → ads).
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.exploration import (
    AdType,
    ExplorationBlueprint,
    ExplorationCoverage,
    ExplorationGoal,
    GoalCoverageItem,
    GoalKind,
    NavigationStep,
)

_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")
_NOISE = {
    "activity",
    "fragment",
    "screen",
    "main",
    "launcher",
    "splash",
    "app",
    "base",
    "ui",
    "view",
    "page",
    "com",
    "android",
}

# Generic UI verbs — NOT product domains (no alarm/timer/shopping hardcoding).
_CREATE_RX = re.compile(
    r"\b(create|add|new|edit|compose|writer|editor|form)\b|"
    r"(^|[^a-z])(set)(?!tings)([A-Z_]|$)",
    re.I,
)
_SETTINGS_RX = re.compile(r"settings|preference|option|config", re.I)
_ONBOARD_RX = re.compile(
    r"onboard|welcome|intro|tutorial|consent|gdpr|permission|login|signin|sign_in",
    re.I,
)
_HOME_RX = re.compile(r"\b(home|dashboard|main|launcherhome)\b", re.I)
_MENU_RX = re.compile(r"\b(menu|drawer|sidebar|navigation|navdrawer)\b", re.I)
_CREATE_VERBS = {"create", "add", "new", "edit", "compose", "set", "make", "write"}

# Static SDK name → expected runtime ad types.
_AD_SDK_EXPECTATIONS: dict[str, tuple[AdType, ...]] = {
    "google admob": ("banner", "interstitial", "rewarded", "native", "app_open"),
    "facebook audience network": ("banner", "interstitial", "native", "rewarded"),
    "ironsource": ("banner", "interstitial", "rewarded"),
    "unity ads": ("banner", "interstitial", "rewarded"),
    "applovin": ("banner", "interstitial", "rewarded", "native"),
    "vungle": ("interstitial", "rewarded"),
    "chartboost": ("interstitial", "rewarded"),
}

_REWARDED_SDKS = {"ironsource", "unity ads", "applovin", "vungle", "chartboost", "google admob"}

_DEFAULT_AD_TRIGGERS = (
    "watch",
    "reward",
    "video",
    "earn",
    "unlock",
    "claim",
    "bonus",
    "free coin",
)

_SIDEBAR_LABELS = (
    "menu",
    "drawer",
    "navigation",
    "open navigation",
    "sidebar",
    "hamburger",
)

# Human-like journey order (lower first).
_KIND_STEP_ORDER: dict[str, int] = {
    "onboarding": 10,
    "create": 20,
    "home": 30,
    "sidebar": 40,
    "destination": 50,
    "feature": 55,
    "settings": 60,
    "ad_trigger": 70,
}


def _as_dict(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def _activity_short(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _tokens(name: str) -> list[str]:
    short = re.sub(
        r"(Activity|Fragment|Screen|Page)$",
        "",
        _activity_short(name),
        flags=re.IGNORECASE,
    )
    parts = _CAMEL_SPLIT.sub(" ", short).replace("_", " ").replace("-", " ").split()
    out: list[str] = []
    for part in parts:
        token = part.strip().lower()
        if len(token) >= 3 and token not in _NOISE:
            out.append(token)
    return out


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = (item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _feature_slug(tokens: list[str]) -> str:
    """Derive feature name from *this* APK's tokens (not a fixed domain list)."""
    rest = [t for t in tokens if t not in _CREATE_VERBS and t not in _NOISE]
    if not rest:
        return "item"
    return "_".join(rest[:2])[:32]


def _build_nav_path(goals: list[ExplorationGoal]) -> list[NavigationStep]:
    ordered = sorted(goals, key=lambda g: (g.step_order, -g.priority, g.id))
    return [
        NavigationStep(goal_id=g.id, order=i, summary=g.title)
        for i, g in enumerate(ordered)
    ]


def mine_blueprint(analysis: Any) -> ExplorationBlueprint:
    """Build a deterministic per-app blueprint from AnalysisResponse / data dict."""
    payload = _as_dict(analysis)
    data = _as_dict(payload.get("data")) or payload
    apk = _as_dict(data.get("apk"))
    manifest = _as_dict(data.get("manifest"))
    package = apk.get("package_name") or manifest.get("package") or data.get("package_name")
    app_label = manifest.get("app_label") or apk.get("file_name")

    activities_raw = data.get("activities") or []
    activity_names: list[str] = []
    for raw in activities_raw:
        entry = _as_dict(raw)
        name = entry.get("name")
        if name and entry.get("enabled") is not False:
            activity_names.append(str(name))

    code = _as_dict(data.get("code_analysis"))
    sdk_usage = code.get("third_party_sdk_usage") or []
    sdk_names: list[str] = []
    for item in sdk_usage:
        entry = _as_dict(item) if not isinstance(item, str) else {"name": item}
        name = entry.get("name") or entry.get("sdk") or entry.get("package")
        if name:
            sdk_names.append(str(name))

    # Richer static: app class simple names act like extra "pages" (no domain lists).
    for raw_cls in code.get("classes") or []:
        entry = _as_dict(raw_cls) if not isinstance(raw_cls, str) else {"name": raw_cls}
        if entry.get("is_app_code") is False:
            continue
        cname = str(entry.get("name") or "")
        if not cname:
            continue
        short = _activity_short(cname)
        lowered = short.lower()
        if any(
            token in lowered
            for token in (
                "activity",
                "fragment",
                "screen",
                "page",
                "menu",
                "drawer",
                "setting",
                "create",
                "edit",
                "compose",
                "home",
                "main",
            )
        ):
            # Synthetic activity path so token mining can see it.
            synthetic = cname if "." in cname else f"{package or 'app'}.{short}"
            if synthetic not in activity_names:
                activity_names.append(synthetic)

    # Path-like tokens from network_strings → preferred labels / destinations (generic).
    route_tokens: list[str] = []
    for item in code.get("network_strings") or []:
        entry = _as_dict(item) if not isinstance(item, str) else {"value": item}
        value = str(entry.get("value") or entry.get("string") or "")
        if not value or len(value) > 120:
            continue
        if "://" in value:
            # Keep path segments after host only.
            value = value.split("://", 1)[-1]
            if "/" in value:
                value = value.split("/", 1)[-1]
            else:
                continue
        for part in re.split(r"[/\-_?&=]+", value):
            token = part.strip().lower()
            if (
                4 <= len(token) <= 24
                and token.isalpha()
                and token not in _NOISE
                and token not in {"http", "https", "www", "api", "com", "json"}
            ):
                route_tokens.append(token)

    ad_sdk_names: list[str] = []
    ad_expectations: list[AdType] = []
    seen_types: set[str] = set()
    for name in sdk_names:
        key = name.lower()
        for sdk_key, types in _AD_SDK_EXPECTATIONS.items():
            if sdk_key in key or key in sdk_key:
                ad_sdk_names.append(name)
                for ad_type in types:
                    if ad_type not in seen_types:
                        seen_types.add(ad_type)
                        ad_expectations.append(ad_type)
                break

    goals: list[ExplorationGoal] = []
    preferred: list[str] = ["add", "create", "new", "save", "home", "menu", "settings"]
    goal_ids: set[str] = set()
    feature_words: list[str] = []

    def _add_goal(goal: ExplorationGoal) -> None:
        if goal.id in goal_ids:
            return
        goal_ids.add(goal.id)
        if goal.step_order == 50 and goal.kind in _KIND_STEP_ORDER:
            goal.step_order = _KIND_STEP_ORDER[goal.kind]
        goals.append(goal)
        preferred.extend(goal.ui_labels)

    for name in activity_names:
        short = _activity_short(name)
        tokens = _tokens(name)
        blob = f"{short} {' '.join(tokens)}"
        if "splash" in blob.lower():
            continue
        feature_words.extend(tokens)

        if _ONBOARD_RX.search(blob):
            _add_goal(
                ExplorationGoal(
                    id=f"onboard_{'_'.join(tokens[:2]) or short.lower()}"[:40],
                    kind="onboarding",
                    title=f"Complete onboarding ({short})",
                    activity_hints=[short, name],
                    ui_labels=_uniq(
                        ["continue", "next", "agree", "allow", "get started", "skip"] + tokens[:4]
                    ),
                    priority=95,
                    step_order=_KIND_STEP_ORDER["onboarding"],
                    why=f"Activity {short} suggests onboarding/consent",
                )
            )
        elif _CREATE_RX.search(blob):
            slug = _feature_slug(tokens)
            labels = _uniq(["create", "add", "new", "save", "done", "ok"] + tokens[:6])
            _add_goal(
                ExplorationGoal(
                    id=f"create_{slug}",
                    kind="create",
                    title=f"Create / set up ({slug.replace('_', ' ')})",
                    activity_hints=[short, name],
                    ui_labels=labels,
                    priority=90,
                    step_order=_KIND_STEP_ORDER["create"],
                    why=f"Activity {short} suggests a create/edit flow for this app",
                )
            )
        elif _SETTINGS_RX.search(blob):
            _add_goal(
                ExplorationGoal(
                    id="settings",
                    kind="settings",
                    title="Open Settings",
                    activity_hints=[short, name],
                    ui_labels=_uniq(["settings", "preference", "options"] + tokens[:3]),
                    expected_ad_types=["banner"] if ad_expectations else [],
                    priority=55,
                    step_order=_KIND_STEP_ORDER["settings"],
                    why=f"Activity {short} looks like settings",
                )
            )
        elif _MENU_RX.search(blob):
            _add_goal(
                ExplorationGoal(
                    id="sidebar_menu",
                    kind="sidebar",
                    title="Open navigation drawer / sidebar",
                    activity_hints=[short, name],
                    ui_labels=_uniq(list(_SIDEBAR_LABELS) + tokens[:3]),
                    priority=70,
                    step_order=_KIND_STEP_ORDER["sidebar"],
                    why=f"Activity {short} suggests drawer/menu navigation",
                )
            )
        elif _HOME_RX.search(blob):
            _add_goal(
                ExplorationGoal(
                    id="home",
                    kind="home",
                    title="Return to / explore home",
                    activity_hints=[short, name],
                    ui_labels=_uniq(["home", "main", "dashboard"] + tokens[:3]),
                    expected_ad_types=["banner"] if "banner" in seen_types else [],
                    priority=75,
                    step_order=_KIND_STEP_ORDER["home"],
                    why=f"Activity {short} looks like home/main",
                )
            )
        elif tokens:
            gid = f"dest_{'_'.join(tokens[:2])}"[:40]
            _add_goal(
                ExplorationGoal(
                    id=gid,
                    kind="destination",
                    title=f"Explore {short}",
                    activity_hints=[short, name],
                    ui_labels=_uniq(tokens[:6]),
                    priority=45,
                    step_order=_KIND_STEP_ORDER["destination"],
                    why=f"Manifest activity {short} — visit this section",
                )
            )

    # Always plan to open the drawer/sidebar if the app has multiple destinations.
    dest_count = sum(1 for g in goals if g.kind in {"destination", "settings", "feature", "home"})
    if "sidebar_menu" not in goal_ids and dest_count >= 1:
        _add_goal(
            ExplorationGoal(
                id="sidebar_menu",
                kind="sidebar",
                title="Open sidebar / menu and explore each section",
                ui_labels=list(_SIDEBAR_LABELS),
                priority=70,
                step_order=_KIND_STEP_ORDER["sidebar"],
                why="Multi-section app — explore drawer/menu like a human",
            )
        )

    # Route tokens from static strings → soft destination hints (this APK only).
    for token in _uniq(route_tokens)[:6]:
        gid = f"dest_{token}"[:40]
        if gid in goal_ids:
            continue
        _add_goal(
            ExplorationGoal(
                id=gid,
                kind="destination",
                title=f"Explore '{token}' (from static strings)",
                ui_labels=[token],
                priority=40,
                step_order=_KIND_STEP_ORDER["destination"],
                why=f"Static string/path token '{token}' in this APK",
            )
        )
        preferred.append(token)

    if "home" not in goal_ids:
        _add_goal(
            ExplorationGoal(
                id="home",
                kind="home",
                title="Reach home / main screen",
                ui_labels=["home", "main"],
                expected_ad_types=["banner"] if "banner" in seen_types else [],
                priority=75,
                step_order=_KIND_STEP_ORDER["home"],
                why="Always return to home between sections when possible",
            )
        )

    needs_rewarded = any(t in seen_types for t in ("rewarded", "interstitial"))
    if needs_rewarded or any(any(s in n.lower() for s in _REWARDED_SDKS) for n in ad_sdk_names):
        _add_goal(
            ExplorationGoal(
                id="ad_triggers",
                kind="ad_trigger",
                title="Trigger rewarded / interstitial ads",
                ui_labels=list(_DEFAULT_AD_TRIGGERS),
                expected_ad_types=[t for t in ("rewarded", "interstitial") if t in seen_types]
                or ["rewarded"],
                priority=50,
                step_order=_KIND_STEP_ORDER["ad_trigger"],
                why="Ad SDK present — visit pages/actions that show ads after core flows",
            )
        )

    if ad_expectations:
        _add_goal(
            ExplorationGoal(
                id="ad_surfaces",
                kind="feature",
                title="Visit pages likely to show ads",
                ui_labels=_uniq(["home", "settings", "main"] + list(_SIDEBAR_LABELS)[:3]),
                expected_ad_types=list(ad_expectations[:4]),
                priority=48,
                step_order=65,
                why="Ad SDK present — cover main chrome after create/home/sidebar",
            )
        )

    # App summary from package/label + distinctive activity tokens (no domain hardcoding).
    distinctive = _uniq([t for t in feature_words if t not in _CREATE_VERBS])[:8]
    summary_bits = []
    if app_label:
        summary_bits.append(str(app_label))
    if package:
        summary_bits.append(str(package))
    if distinctive:
        summary_bits.append("features: " + ", ".join(distinctive))
    if ad_sdk_names:
        summary_bits.append("ads: " + ", ".join(_uniq(ad_sdk_names)[:4]))

    ad_trigger_labels = list(_DEFAULT_AD_TRIGGERS) if needs_rewarded else []
    preferred_labels = _uniq(preferred + list(_SIDEBAR_LABELS) + list(ad_trigger_labels))
    nav_path = _build_nav_path(goals)
    goals.sort(key=lambda g: (g.step_order, -g.priority, g.id))

    return ExplorationBlueprint(
        package_name=str(package) if package else None,
        app_summary="; ".join(summary_bits) if summary_bits else None,
        goals=goals,
        nav_path=nav_path,
        ad_expectations=ad_expectations,
        ad_sdk_names=_uniq(ad_sdk_names),
        preferred_labels=preferred_labels,
        ad_trigger_labels=ad_trigger_labels,
        source="deterministic",
    )


def apply_blueprint_to_prior(prior: Any, blueprint: ExplorationBlueprint) -> None:
    """Merge blueprint labels/goals/nav_path onto an ExplorationPrior in place."""
    if prior is None or blueprint is None:
        return
    prior.goals = [g.model_dump() for g in blueprint.goals]
    prior.ad_expectations = list(blueprint.ad_expectations)
    prior.ad_trigger_labels = list(blueprint.ad_trigger_labels)
    prior.nav_path = [s.model_dump() for s in blueprint.nav_path]
    prior.blueprint = blueprint.model_dump()
    merged = _uniq(list(blueprint.preferred_labels) + list(prior.preferred_labels or []))
    prior.preferred_labels = merged
    extras = dict(prior.extras or {})
    extras["blueprint_source"] = blueprint.source
    extras["ad_sdk_names"] = list(blueprint.ad_sdk_names)
    extras["app_summary"] = blueprint.app_summary
    prior.extras = extras


def build_coverage(
    blueprint: ExplorationBlueprint | dict[str, Any] | None,
    *,
    covered_goal_ids: set[str] | dict[str, list[str]] | None = None,
    ad_types_found: list[str] | None = None,
) -> ExplorationCoverage:
    """Summarize goal / ad-type coverage for the job result."""
    if blueprint is None:
        return ExplorationCoverage()
    if isinstance(blueprint, dict):
        bp = ExplorationBlueprint.model_validate(blueprint)
    else:
        bp = blueprint

    evidence_map: dict[str, list[str]] = {}
    covered_set: set[str] = set()
    if isinstance(covered_goal_ids, dict):
        evidence_map = {k: list(v) for k, v in covered_goal_ids.items()}
        covered_set = set(evidence_map)
    elif covered_goal_ids:
        covered_set = set(covered_goal_ids)

    found = _uniq([str(t) for t in (ad_types_found or []) if t and t != "unknown"])
    expected = [str(t) for t in bp.ad_expectations]
    missing = [t for t in expected if t not in found]

    items: list[GoalCoverageItem] = []
    for goal in bp.goals:
        covered = goal.id in covered_set or goal.covered
        items.append(
            GoalCoverageItem(
                goal_id=goal.id,
                title=goal.title,
                kind=goal.kind,
                covered=covered,
                evidence=evidence_map.get(goal.id, []),
            )
        )
    covered_count = sum(1 for item in items if item.covered)
    return ExplorationCoverage(
        goals=items,
        ad_types_expected=expected,
        ad_types_found=found,
        ad_types_missing=missing,
        goals_covered=covered_count,
        goals_total=len(items),
    )


def match_goals_for_screen(
    goals: list[dict[str, Any]] | list[ExplorationGoal],
    *,
    activity: str | None,
    ui_blob: str = "",
    action_kind: str | None = None,
    last_label: str | None = None,
    screen_role: str | None = None,
) -> list[str]:
    """Return goal ids that appear matched by current activity / UI text.

    Kind-based strictness (domain-agnostic):
    - create: needs create/edit activity OR (save/done/create submit evidence)
    - sidebar: needs drawer-open evidence (not bare 'menu')
    - destination/feature: label or activity hint
    """
    matched: list[str] = []
    act = (activity or "").lower()
    blob = f"{act} {ui_blob}".lower()
    last = (last_label or "").lower()
    action = (action_kind or "").lower()
    role = (screen_role or "").lower()

    for raw in goals:
        goal = raw if isinstance(raw, ExplorationGoal) else ExplorationGoal.model_validate(raw)
        hit = False
        activity_hit = False
        for hint in goal.activity_hints:
            if hint and hint.lower() in act:
                activity_hit = True
                hit = True
                break

        if goal.kind == "create":
            submit_evidence = any(
                token in blob or token in last
                for token in ("save", "done", "create", "submit")
            )
            # Strict: create/edit activity with submit chrome, or explicit Save/Done tap.
            if activity_hit and (submit_evidence or "create" in act or "edit" in act):
                hit = True
            elif ("save" in last or "done" in last) and (
                activity_hit
                or any(
                    lab.lower() in blob
                    for lab in goal.ui_labels
                    if lab and lab.lower() not in {"new", "add", "ok", "item"}
                )
            ):
                hit = True
            else:
                hit = False

        elif goal.kind == "sidebar":
            hit = False
            if role == "drawer_open" or any(
                token in blob
                for token in (
                    "drawer",
                    "navigation drawer",
                    "nav_drawer",
                    "nav_view",
                    "sidebar",
                    "open_menu",
                )
            ):
                hit = True
            if action == "open_menu":
                hit = True

        elif goal.kind == "onboarding":
            if activity_hit:
                hit = True
            elif any(
                lab and len(lab) >= 3 and lab.lower() in blob
                for lab in goal.ui_labels
            ) and any(t in blob for t in ("continue", "next", "agree", "allow", "started")):
                hit = True

        elif goal.kind == "home":
            if activity_hit or role == "home":
                hit = True
            elif "home" in blob and (
                action == "tap" or "home" in last or "main" in act
            ):
                hit = True
            else:
                hit = activity_hit

        elif goal.kind == "settings":
            if activity_hit or "setting" in act:
                hit = True
            elif "setting" in last or (
                "setting" in blob and action == "tap"
            ):
                hit = True
            else:
                hit = False

        elif goal.kind in {"destination", "feature"}:
            hit = activity_hit
            if not hit:
                for label in goal.ui_labels:
                    if label and len(label) >= 3 and label.lower() in blob:
                        hit = True
                        break
            # Section goals: require the section label itself, not weak substrings.
            if goal.id.startswith("section_") and not activity_hit:
                hit = any(
                    lab and len(lab) >= 2 and lab.lower() in (last or blob)
                    for lab in goal.ui_labels
                )

        elif goal.kind == "ad_trigger":
            hit = any(
                lab and len(lab) >= 3 and lab.lower() in blob for lab in goal.ui_labels
            )

        elif not hit and goal.kind != "sidebar":
            for label in goal.ui_labels:
                if label and len(label) >= 3 and label.lower() in blob:
                    hit = True
                    break

        if hit:
            matched.append(goal.id)
    return matched


def tag_ad_placement(
    placement: Any,
    *,
    blueprint: ExplorationBlueprint | dict[str, Any] | None,
    activity: str | None = None,
) -> None:
    """Annotate an AdPlacement (model or dict-like) with blueprint expectations."""
    if placement is None or blueprint is None:
        return
    bp = (
        ExplorationBlueprint.model_validate(blueprint)
        if isinstance(blueprint, dict)
        else blueprint
    )
    ad_type = getattr(placement, "ad_type", None)
    if ad_type is None and isinstance(placement, dict):
        ad_type = placement.get("ad_type")
    ad_type_s = str(ad_type or "unknown")
    expected = ad_type_s in {str(t) for t in bp.ad_expectations}
    matched: list[str] = []
    for goal in bp.goals:
        if ad_type_s in {str(t) for t in goal.expected_ad_types}:
            matched.append(goal.id)
        elif goal.kind == "ad_trigger" and ad_type_s in {"rewarded", "interstitial"}:
            matched.append(goal.id)
        elif goal.kind in {"settings", "destination", "feature", "home", "sidebar"} and ad_type_s == "banner":
            if any(
                h and activity and h.lower() in activity.lower()
                for h in goal.activity_hints
            ) or goal.kind in {"home", "sidebar", "feature"}:
                matched.append(goal.id)
    matched = _uniq(matched)
    if hasattr(placement, "expected_from_sdk"):
        placement.expected_from_sdk = expected
        placement.matched_goals = matched
    elif isinstance(placement, dict):
        placement["expected_from_sdk"] = expected
        placement["matched_goals"] = matched
