from __future__ import annotations

from app.core.xmlutil import android_attr, children_by_tag, parse_int
from app.modules.apk_analyzer.context import ApkContext
from app.modules.permissions.aosp import aosp_protection_level

_PROTECTION_LEVEL_MAP = {
    "0": "normal",
    "1": "dangerous",
    "2": "signature",
    "3": "signatureOrSystem",
    "normal": "normal",
    "dangerous": "dangerous",
    "signature": "signature",
    "signatureorsystem": "signatureOrSystem",
    "signature|privileged": "signature|privileged",
    "privileged": "privileged",
}


def _normalize_protection(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if key in _PROTECTION_LEVEL_MAP:
        return _PROTECTION_LEVEL_MAP[key]
    if raw.strip() in _PROTECTION_LEVEL_MAP:
        return _PROTECTION_LEVEL_MAP[raw.strip()]
    return raw


def extract_permissions(ctx: ApkContext) -> list[dict]:
    declared: dict[str, str | None] = {}
    for el in children_by_tag(ctx.manifest_xml, "permission"):
        name = android_attr(el, "name")
        if not name:
            continue
        declared[name] = _normalize_protection(android_attr(el, "protectionLevel"))

    results: list[dict] = []
    seen: set[str] = set()
    for el in children_by_tag(ctx.manifest_xml, "uses-permission"):
        name = android_attr(el, "name")
        if not name or name in seen:
            continue
        seen.add(name)
        max_sdk = parse_int(android_attr(el, "maxSdkVersion"))
        if name in declared and declared[name]:
            protection, source = declared[name], "manifest"
        else:
            mapped = aosp_protection_level(name)
            protection, source = (mapped, "aosp_mapping") if mapped else (None, None)
        results.append(
            {
                "name": name,
                "max_sdk_version": max_sdk,
                "protection_level": protection,
                "protection_level_source": source,
            }
        )

    if not results:
        try:
            for name in ctx.apk.get_permissions() or []:
                if name in seen:
                    continue
                seen.add(name)
                mapped = aosp_protection_level(name)
                results.append(
                    {
                        "name": name,
                        "max_sdk_version": None,
                        "protection_level": mapped,
                        "protection_level_source": "aosp_mapping" if mapped else None,
                    }
                )
        except Exception:
            pass

    aapt = getattr(ctx, "aapt", None) or {}
    added = 0
    for item in aapt.get("permissions") or []:
        name = item.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        mapped = aosp_protection_level(name)
        results.append(
            {
                "name": name,
                "max_sdk_version": item.get("max_sdk_version"),
                "protection_level": mapped,
                "protection_level_source": "aosp_mapping" if mapped else None,
            }
        )
        added += 1
    if added:
        ctx.warnings.append(f"{added} permission(s) were added from aapt dump badging.")

    return results
