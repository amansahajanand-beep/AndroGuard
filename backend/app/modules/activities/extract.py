from __future__ import annotations

from app.core.xmlutil import (
    android_attr,
    children_by_tag,
    find_application,
    parse_bool,
    resolve_component_name,
)
from app.modules.apk_analyzer.context import ApkContext
from app.modules.components.exported import resolve_exported
from app.modules.components.intent_filters import extract_intent_filters


def extract_activities(ctx: ApkContext, target_sdk: int | None) -> list[dict]:
    app = find_application(ctx.manifest_xml)
    if app is None:
        return []
    package = android_attr(ctx.manifest_xml, "package") or ""
    results: list[dict] = []
    for tag in ("activity", "activity-alias"):
        for el in children_by_tag(app, tag):
            raw_name = android_attr(el, "name") or android_attr(el, "targetActivity")
            name = resolve_component_name(package, raw_name)
            if not name:
                continue
            filters = extract_intent_filters(el)
            exported, inferred, warning = resolve_exported(
                parse_bool(android_attr(el, "exported")),
                bool(filters),
                target_sdk,
            )
            if warning:
                ctx.warnings.append(f"{name}: {warning}")
            enabled = parse_bool(android_attr(el, "enabled"))
            results.append(
                {
                    "name": name,
                    "exported": exported,
                    "exported_inferred": inferred,
                    "enabled": True if enabled is None else enabled,
                    "permission": android_attr(el, "permission"),
                    "direct_boot_aware": parse_bool(android_attr(el, "directBootAware")),
                    "process": android_attr(el, "process"),
                    "launch_mode": android_attr(el, "launchMode"),
                    "theme": android_attr(el, "theme"),
                    "intent_filters": filters,
                }
            )
    return results
