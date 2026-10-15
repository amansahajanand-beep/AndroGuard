"""Prior knowledge extracted from the *existing* APK analysis JSON.

Static analysis already knows package, activities and the launcher. Phase 4
uses that as a bias for exploration — it does not re-parse the APK from scratch
or invent a navigation map that the analyzer never produced.

What the analyzer typically provides today:

* package name
* activity list + MAIN/LAUNCHER
* optional DEX / third-party SDK hints

Fragments, buttons and runtime screens are **not** in the static JSON; those
come from live UIAutomator dumps. We still seed preferred tap labels from
activity short names (e.g. ``SettingsActivity`` → prefer taps containing
``settings``) so known destinations are tried first.

Code-aware blueprints (activities + ad SDKs → goals) further bias labels and
coverage tracking without inventing ADB actions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.modules.exploration.target import LaunchTarget, launcher_activity, target_from_analysis

_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")
_NOISE_TOKENS = {
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
}


def _as_dict(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def _activity_short_name(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _tokens_from_name(name: str) -> list[str]:
    short = _activity_short_name(name)
    short = re.sub(r"(Activity|Fragment|Screen|Page)$", "", short, flags=re.IGNORECASE)
    parts = _CAMEL_SPLIT.sub(" ", short).replace("_", " ").replace("-", " ").split()
    tokens: list[str] = []
    for part in parts:
        token = part.strip().lower()
        if len(token) < 3 or token in _NOISE_TOKENS:
            continue
        tokens.append(token)
    return tokens


@dataclass
class ExplorationPrior:
    """Prior knowledge the explorer consults before blind UI crawling."""

    package_name: str
    launch_activity: str | None = None
    activities: list[str] = field(default_factory=list)
    preferred_labels: list[str] = field(default_factory=list)
    sdk_hints: list[str] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    nav_path: list[dict[str, Any]] = field(default_factory=list)
    ad_expectations: list[str] = field(default_factory=list)
    ad_trigger_labels: list[str] = field(default_factory=list)
    covered_goal_evidence: dict[str, list[str]] = field(default_factory=dict)
    blueprint: dict[str, Any] | None = None
    source: str = "static_analysis"
    extras: dict[str, Any] = field(default_factory=dict)
    # Phase 12J — shared region coverage memory (runtime; set by Explorer).
    region_memory: Any | None = None

    @property
    def launch_target(self) -> LaunchTarget:
        return LaunchTarget(
            package_name=self.package_name,
            activity=self.launch_activity,
            source=self.source,
        )

    def uncovered_goals(self) -> list[dict[str, Any]]:
        covered = set(self.covered_goal_evidence)
        return [g for g in self.goals if g.get("id") not in covered]

    def active_goal(self) -> dict[str, Any] | None:
        """Next goal in the human-like nav_path that is still uncovered."""
        covered = set(self.covered_goal_evidence)
        by_id = {g.get("id"): g for g in self.goals if g.get("id")}
        if self.nav_path:
            for step in sorted(self.nav_path, key=lambda s: int(s.get("order") or 0)):
                gid = step.get("goal_id")
                if gid and gid not in covered and gid in by_id:
                    return by_id[gid]
        uncovered = self.uncovered_goals()
        if not uncovered:
            return None
        return sorted(
            uncovered,
            key=lambda g: (int(g.get("step_order") or 50), -int(g.get("priority") or 0)),
        )[0]

    def wants_ad_triggers(self) -> bool:
        """True when blueprint expects rewarded/interstitial — bias trigger labels."""
        expected = {str(t).lower() for t in self.ad_expectations}
        if expected & {"rewarded", "interstitial"}:
            # Only after earlier journey steps are mostly done.
            active = self.active_goal()
            if active and active.get("kind") in {
                "onboarding",
                "create",
                "home",
                "sidebar",
            }:
                return False
            return True
        return any(g.get("kind") == "ad_trigger" for g in self.uncovered_goals())

    def skip_goal(self, goal_id: str, *, reason: str = "skipped") -> None:
        """Mark a goal done-enough to advance the journey (budget / unblock)."""
        if not goal_id:
            return
        bucket = self.covered_goal_evidence.setdefault(goal_id, [])
        note = f"skip:{reason}"[:120]
        if note not in bucket:
            bucket.append(note)

    def mark_goal_coverage(
        self,
        *,
        activity: str | None = None,
        ui_blob: str = "",
        evidence: str | None = None,
        action_kind: str | None = None,
        last_label: str | None = None,
        screen_role: str | None = None,
    ) -> list[str]:
        """Mark goals matched by the current screen; return newly covered ids."""
        from app.modules.exploration.blueprint import match_goals_for_screen

        matched = match_goals_for_screen(
            self.goals,
            activity=activity,
            ui_blob=ui_blob,
            action_kind=action_kind,
            last_label=last_label,
            screen_role=screen_role,
        )
        note = evidence or (activity or "screen")[:120]
        newly: list[str] = []
        for goal_id in matched:
            bucket = self.covered_goal_evidence.setdefault(goal_id, [])
            if note not in bucket:
                bucket.append(note)
                newly.append(goal_id)
            if len(bucket) > 6:
                del bucket[6:]
        return newly

    def label_priority(self, text: str, resource_id: str = "", content_description: str = "") -> int:
        """Higher score = try this tap earlier (active nav-map goal first)."""
        haystack = " ".join([text or "", resource_id or "", content_description or ""]).lower()
        if not haystack:
            return 0
        score = 0
        for label in self.preferred_labels:
            if label and label.lower() in haystack:
                score += 8 + min(len(label), 10)

        active = self.active_goal()
        if active:
            for label in active.get("ui_labels") or []:
                if label and len(str(label)) >= 2 and str(label).lower() in haystack:
                    score += 40 + min(int(active.get("priority") or 50) // 4, 25)
                    break
            kind = active.get("kind")
            if kind == "sidebar" and any(
                token in haystack
                for token in (
                    "drawer",
                    "navigation drawer",
                    "hamburger",
                    "sidebar",
                    "open navigation",
                    "open menu",
                )
            ):
                score += 50
            # Do not treat per-row "more options" as sidebar progress.
            if kind == "sidebar" and any(
                token in haystack for token in ("more options", "morebutton", "overflow")
            ):
                score -= 40
            if kind == "home" and "home" in haystack:
                score += 45
            if kind == "create" and any(
                token in haystack for token in ("add", "create", "save", "new", "fab")
            ):
                score += 45

        for goal in self.uncovered_goals():
            if active and goal.get("id") == active.get("id"):
                continue
            priority = int(goal.get("priority") or 50)
            for label in goal.get("ui_labels") or []:
                if label and len(str(label)) >= 2 and str(label).lower() in haystack:
                    score += 10 + min(priority // 6, 15)
                    break
        for label in self.ad_trigger_labels:
            if self.wants_ad_triggers() and label and label.lower() in haystack:
                score += 12
        return score

    def plan_summary_for_ai(self, *, max_goals: int = 10) -> str:
        """Trusted compact plan text for Phase 10 prompts."""
        lines: list[str] = []
        summary = (self.extras or {}).get("app_summary")
        if summary:
            lines.append(f"App (from code): {summary}")
        active = self.active_goal()
        if active:
            labels = ", ".join((active.get("ui_labels") or [])[:8])
            lines.append(
                f"ACTIVE next step: {active.get('id')} — {active.get('title')} "
                f"[kind={active.get('kind')}] seek labels=[{labels}]"
            )
        if self.nav_path:
            lines.append("Ordered nav map (follow in order; skip covered):")
            covered = set(self.covered_goal_evidence)
            for step in sorted(self.nav_path, key=lambda s: int(s.get("order") or 0))[:max_goals]:
                gid = step.get("goal_id")
                mark = "done" if gid in covered else "todo"
                lines.append(
                    f"  {int(step.get('order') or 0)}. [{mark}] {gid}: {step.get('summary') or ''}"
                )
        uncovered = self.uncovered_goals()[:max_goals]
        if uncovered and not self.nav_path:
            lines.append("Uncovered goals:")
            for goal in uncovered:
                labels = ", ".join((goal.get("ui_labels") or [])[:6])
                lines.append(
                    f"- {goal.get('id')}: {goal.get('title')} "
                    f"[kind={goal.get('kind')}] labels=[{labels}]"
                )
        if self.ad_expectations:
            lines.append(
                "Expected ad types from SDKs: " + ", ".join(str(t) for t in self.ad_expectations)
            )
        lines.append(
            "Behave like a human tester: finish active step, then home/sidebar sections, "
            "then settings; never tap Install/ad creatives; prefer Close/Skip/Back for ads; "
            "open menu/drawer to explore each section."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "launch_activity": self.launch_activity,
            "activities": list(self.activities),
            "preferred_labels": list(self.preferred_labels),
            "sdk_hints": list(self.sdk_hints),
            "goals": list(self.goals),
            "nav_path": list(self.nav_path),
            "ad_expectations": list(self.ad_expectations),
            "ad_trigger_labels": list(self.ad_trigger_labels),
            "covered_goal_evidence": {
                k: list(v) for k, v in self.covered_goal_evidence.items()
            },
            "blueprint": dict(self.blueprint) if self.blueprint else None,
            "source": self.source,
            "extras": dict(self.extras),
        }


def prior_from_analysis(analysis: Any) -> ExplorationPrior | None:
    """Build prior knowledge from an AnalysisResponse / dumped JSON / data dict."""
    target = target_from_analysis(analysis)
    if target is None:
        return None

    payload = _as_dict(analysis)
    data = _as_dict(payload.get("data")) or payload
    activities_raw = data.get("activities") or []
    activity_names: list[str] = []
    for raw in activities_raw:
        entry = _as_dict(raw)
        name = entry.get("name")
        if name and entry.get("enabled") is not False:
            activity_names.append(name)

    if not activity_names and target.activity:
        activity_names = [target.activity]

    labels = _preferred_labels(activity_names)
    sdk_hints = _sdk_hints(data)

    prior = ExplorationPrior(
        package_name=target.package_name,
        launch_activity=target.activity or launcher_activity(activities_raw),
        activities=activity_names,
        preferred_labels=labels,
        sdk_hints=sdk_hints,
        source=target.source,
        extras={
            "activity_count": len(activity_names),
            "has_code_analysis": bool(data.get("code_analysis")),
        },
    )

    try:
        from app.modules.ai_explorer.plan_enricher import build_exploration_blueprint
        from app.modules.exploration.blueprint import apply_blueprint_to_prior

        blueprint = build_exploration_blueprint(analysis)
        apply_blueprint_to_prior(prior, blueprint)
    except Exception:
        # Blueprint is advisory — never block exploration.
        pass

    return prior


def prior_from_package(
    package_name: str,
    *,
    activity: str | None = None,
    activities: Iterable[str] | None = None,
) -> ExplorationPrior:
    """Minimal prior when only package/activity are known (CLI smoke)."""
    names = list(activities or ([] if not activity else [activity]))
    return ExplorationPrior(
        package_name=package_name,
        launch_activity=activity,
        activities=names,
        preferred_labels=_preferred_labels(names),
        source="explicit",
    )


def _preferred_labels(activity_names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    # Generic UI verbs only — product nouns come from this APK's activity tokens.
    for seed in (
        "add",
        "create",
        "new",
        "save",
        "done",
        "settings",
        "home",
        "menu",
        "next",
        "continue",
    ):
        seen.add(seed)
        ordered.append(seed)
    for name in activity_names:
        for token in _tokens_from_name(name):
            if token not in seen:
                seen.add(token)
                ordered.append(token)
        short = _activity_short_name(name).lower()
        if short and short not in seen and len(short) >= 4:
            seen.add(short)
            ordered.append(short)
    return ordered


def _sdk_hints(data: dict[str, Any]) -> list[str]:
    code = _as_dict(data.get("code_analysis"))
    usage = code.get("third_party_sdk_usage") or []
    hints: list[str] = []
    for item in usage:
        entry = _as_dict(item) if not isinstance(item, str) else {"name": item}
        name = entry.get("name") or entry.get("sdk") or entry.get("package")
        if name:
            hints.append(str(name))
    return hints
