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
    source: str = "static_analysis"
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def launch_target(self) -> LaunchTarget:
        return LaunchTarget(
            package_name=self.package_name,
            activity=self.launch_activity,
            source=self.source,
        )

    def label_priority(self, text: str, resource_id: str = "", content_description: str = "") -> int:
        """Higher score = try this tap earlier (matches known activity tokens)."""
        haystack = " ".join([text or "", resource_id or "", content_description or ""]).lower()
        if not haystack or not self.preferred_labels:
            return 0
        score = 0
        for label in self.preferred_labels:
            if label and label in haystack:
                score += 10 + min(len(label), 12)
        return score

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "launch_activity": self.launch_activity,
            "activities": list(self.activities),
            "preferred_labels": list(self.preferred_labels),
            "sdk_hints": list(self.sdk_hints),
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

    return ExplorationPrior(
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
