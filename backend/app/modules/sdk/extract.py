from __future__ import annotations

from app.core.xmlutil import android_attr, children_by_tag, parse_int
from app.modules.apk_analyzer.aapt import prefer
from app.modules.apk_analyzer.context import ApkContext
from app.modules.sdk.platforms import platform_name


def _sdk_from_apk(ctx: ApkContext, getter: str) -> int | None:
    try:
        value = getattr(ctx.apk, getter)()
    except Exception:
        return None
    return parse_int(str(value) if value is not None else None)


def extract_sdk(ctx: ApkContext) -> dict:
    min_sdk = None
    target_sdk = None
    max_sdk = None
    for uses_sdk in children_by_tag(ctx.manifest_xml, "uses-sdk"):
        min_sdk = parse_int(android_attr(uses_sdk, "minSdkVersion")) or min_sdk
        target_sdk = parse_int(android_attr(uses_sdk, "targetSdkVersion")) or target_sdk
        max_sdk = parse_int(android_attr(uses_sdk, "maxSdkVersion")) or max_sdk

    if min_sdk is None:
        min_sdk = _sdk_from_apk(ctx, "get_min_sdk_version")
    if target_sdk is None:
        target_sdk = _sdk_from_apk(ctx, "get_target_sdk_version")
    if max_sdk is None:
        max_sdk = _sdk_from_apk(ctx, "get_max_sdk_version")

    compile_sdk = parse_int(android_attr(ctx.manifest_xml, "compileSdkVersion"))
    if compile_sdk is None:
        compile_sdk = parse_int(android_attr(ctx.manifest_xml, "compileSdkVersionCodename"))

    aapt = getattr(ctx, "aapt", None) or {}
    min_sdk = prefer(aapt.get("min_sdk"), min_sdk, "min_sdk", ctx.warnings)
    target_sdk = prefer(aapt.get("target_sdk"), target_sdk, "target_sdk", ctx.warnings)
    if aapt.get("compile_sdk") is not None:
        compile_sdk = prefer(aapt.get("compile_sdk"), compile_sdk, "compile_sdk", ctx.warnings)

    return {
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
        "max_sdk": max_sdk,
        "compile_sdk": compile_sdk,
        "min_platform": platform_name(min_sdk),
        "target_platform": platform_name(target_sdk),
    }
