from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAIN_ACTION = "android.intent.action.MAIN"
LAUNCHER_CATEGORIES = {
    "android.intent.category.LAUNCHER",
    "android.intent.category.LEANBACK_LAUNCHER",
    "android.intent.category.CAR_LAUNCHER",
}


@dataclass
class LaunchTarget:
    """What to install and start on the device."""

    package_name: str
    activity: str | None = None
    source: str = "static_analysis"

    @property
    def is_complete(self) -> bool:
        return bool(self.package_name and self.activity)


def _as_dict(value: Any) -> dict:
    """Accept either a Pydantic model or a plain dict."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def launcher_activity(activities: Any) -> str | None:
    """Find the MAIN/LAUNCHER activity in extracted activity records.

    Consumes the output of the existing ``extract_activities`` (or the
    equivalent slice of an analysis response) without modifying it.
    """
    items = activities or []
    fallback: str | None = None
    for raw in items:
        entry = _as_dict(raw)
        name = entry.get("name")
        if not name:
            continue
        if entry.get("enabled") is False:
            continue
        for raw_filter in entry.get("intent_filters") or []:
            data = _as_dict(raw_filter)
            actions = set(data.get("actions") or [])
            categories = set(data.get("categories") or [])
            if MAIN_ACTION in actions and categories & LAUNCHER_CATEGORIES:
                return name
            if MAIN_ACTION in actions and fallback is None:
                # MAIN without LAUNCHER is a weaker signal; keep it in reserve.
                fallback = name
    return fallback


def target_from_analysis(result: Any) -> LaunchTarget | None:
    """Derive the launch target from an existing analysis payload.

    ``result`` may be an ``AnalysisResponse``, its ``model_dump()``, or the
    inner ``data`` mapping.
    """
    payload = _as_dict(result)
    data = _as_dict(payload.get("data")) or payload
    apk = _as_dict(data.get("apk"))
    manifest = _as_dict(data.get("manifest"))

    package = apk.get("package_name") or manifest.get("package")
    if not package:
        return None
    activity = launcher_activity(data.get("activities"))
    return LaunchTarget(
        package_name=package,
        activity=activity,
        source="static_analysis" if activity else "static_analysis_partial",
    )


def target_from_apk(apk_path: str | Path) -> LaunchTarget:
    """Parse the APK directly, reusing the existing extraction modules.

    Used by the smoke test, where no analysis job has run yet. The API/worker
    path should prefer :func:`target_from_analysis` to avoid parsing twice.
    """
    from app.modules.activities import extract_activities
    from app.modules.apk_analyzer import open_apk
    from app.modules.manifest import extract_manifest
    from app.modules.sdk import extract_sdk

    path = Path(apk_path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    ctx = open_apk(
        path,
        file_name=path.name,
        file_size=path.stat().st_size,
        sha256=digest.hexdigest(),
        job_id="launch-target",
    )
    manifest = extract_manifest(ctx)
    sdk = extract_sdk(ctx)
    activities = extract_activities(ctx, sdk.get("target_sdk"))
    package = manifest.get("package")
    if not package:
        raise ValueError("The APK manifest does not declare a package name.")
    activity = launcher_activity(activities)
    return LaunchTarget(
        package_name=package,
        activity=activity,
        source="apk_manifest" if activity else "apk_manifest_partial",
    )
