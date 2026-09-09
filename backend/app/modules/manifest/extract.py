from __future__ import annotations

from app.core.xmlutil import (
    android_attr,
    children_by_tag,
    find_application,
    parse_bool,
    parse_int,
)
from app.modules.apk_analyzer.aapt import prefer
from app.modules.apk_analyzer.context import ApkContext


def _label_from_apk(ctx: ApkContext) -> str | None:
    try:
        name = ctx.apk.get_app_name()
    except Exception:
        return None
    if not name:
        return None
    if isinstance(name, str) and name.startswith("@"):
        ctx.warnings.append("Application label is an unresolved resource reference.")
        return name
    return str(name)


def extract_manifest(ctx: ApkContext) -> dict:
    manifest = ctx.manifest_xml
    package = android_attr(manifest, "package") or getattr(ctx.apk, "get_package", lambda: None)()
    version_name = android_attr(manifest, "versionName")
    version_code = parse_int(android_attr(manifest, "versionCode"))
    if version_name is None:
        try:
            version_name = ctx.apk.get_androidversion_name()
        except Exception:
            version_name = None
    if version_code is None:
        try:
            version_code = parse_int(str(ctx.apk.get_androidversion_code()))
        except Exception:
            version_code = None

    app = find_application(manifest)
    app_label = None
    debuggable = None
    allow_backup = None
    extract_native = None
    uses_cleartext = None
    app_attrs: dict[str, str] = {}
    if app is not None:
        app_label = android_attr(app, "label")
        debuggable = parse_bool(android_attr(app, "debuggable"))
        allow_backup = parse_bool(android_attr(app, "allowBackup"))
        extract_native = parse_bool(android_attr(app, "extractNativeLibs"))
        uses_cleartext = parse_bool(android_attr(app, "usesCleartextTraffic"))
        for key, value in app.attrib.items():
            short = key.split("}", 1)[-1]
            if value is not None:
                app_attrs[short] = value

    if not app_label or (isinstance(app_label, str) and app_label.startswith("@")):
        resolved = _label_from_apk(ctx)
        if resolved:
            app_label = resolved

    features = []
    for el in children_by_tag(manifest, "uses-feature"):
        features.append(
            {
                "name": android_attr(el, "name"),
                "required": parse_bool(android_attr(el, "required")),
                "gl_es_version": android_attr(el, "glEsVersion"),
            }
        )

    libraries = []
    for el in children_by_tag(manifest, "uses-library"):
        libraries.append(
            {
                "name": android_attr(el, "name"),
                "required": parse_bool(android_attr(el, "required")),
            }
        )

    install_location = android_attr(manifest, "installLocation")
    shared_user_id = android_attr(manifest, "sharedUserId")

    aapt = getattr(ctx, "aapt", None) or {}
    package = prefer(aapt.get("package"), package, "package", ctx.warnings)
    version_name = prefer(aapt.get("version_name"), version_name, "version_name", ctx.warnings)
    version_code = prefer(aapt.get("version_code"), version_code, "version_code", ctx.warnings)
    if aapt.get("app_label"):
        app_label = prefer(aapt.get("app_label"), app_label, "app_label", ctx.warnings)

    return {
        "package": package,
        "app_label": app_label,
        "version_name": version_name,
        "version_code": version_code,
        "debuggable": debuggable,
        "allow_backup": allow_backup,
        "extract_native_libs": extract_native,
        "uses_cleartext_traffic": uses_cleartext,
        "install_location": install_location,
        "shared_user_id": shared_user_id,
        "uses_feature": features,
        "uses_library": libraries,
        "attributes": app_attrs,
    }
