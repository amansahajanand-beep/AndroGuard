from types import SimpleNamespace
from xml.etree.ElementTree import Element, SubElement

from app.core.xmlutil import ANDROID_NS
from app.modules.activities.extract import extract_activities
from app.modules.manifest.extract import extract_manifest
from app.modules.metadata.extract import extract_metadata
from app.modules.permissions.extract import extract_permissions
from app.modules.sdk.extract import extract_sdk
from app.modules.services.extract import extract_services

NS = f"{{{ANDROID_NS}}}"


class DummyApk:
    def get_package(self):
        return "com.example.app"

    def get_app_name(self):
        return "Example App"

    def get_androidversion_name(self):
        return "1.0.0"

    def get_androidversion_code(self):
        return 1

    def get_min_sdk_version(self):
        return "23"

    def get_target_sdk_version(self):
        return "35"

    def get_permissions(self):
        return []


def _manifest() -> Element:
    manifest = Element("manifest")
    manifest.set("package", "com.example.app")
    manifest.set(f"{NS}versionName", "1.0.0")
    manifest.set(f"{NS}versionCode", "2")
    uses_sdk = SubElement(manifest, "uses-sdk")
    uses_sdk.set(f"{NS}minSdkVersion", "23")
    uses_sdk.set(f"{NS}targetSdkVersion", "35")
    perm = SubElement(manifest, "uses-permission")
    perm.set(f"{NS}name", "android.permission.INTERNET")
    camera = SubElement(manifest, "uses-permission")
    camera.set(f"{NS}name", "android.permission.CAMERA")
    custom = SubElement(manifest, "permission")
    custom.set(f"{NS}name", "com.example.CUSTOM")
    custom.set(f"{NS}protectionLevel", "signature")
    uses_custom = SubElement(manifest, "uses-permission")
    uses_custom.set(f"{NS}name", "com.example.CUSTOM")
    feature = SubElement(manifest, "uses-feature")
    feature.set(f"{NS}name", "android.hardware.camera")
    feature.set(f"{NS}required", "true")
    app = SubElement(manifest, "application")
    app.set(f"{NS}label", "Example App")
    app.set(f"{NS}debuggable", "false")
    app.set(f"{NS}allowBackup", "true")
    md_str = SubElement(app, "meta-data")
    md_str.set(f"{NS}name", "com.example.CONFIG")
    md_str.set(f"{NS}value", "prod")
    md_bool = SubElement(app, "meta-data")
    md_bool.set(f"{NS}name", "com.example.FLAG")
    md_bool.set(f"{NS}value", "true")
    md_int = SubElement(app, "meta-data")
    md_int.set(f"{NS}name", "com.example.COUNT")
    md_int.set(f"{NS}value", "7")
    md_res = SubElement(app, "meta-data")
    md_res.set(f"{NS}name", "com.example.ICON")
    md_res.set(f"{NS}resource", "@drawable/icon")
    activity = SubElement(app, "activity")
    activity.set(f"{NS}name", ".MainActivity")
    activity.set(f"{NS}exported", "true")
    intent = SubElement(activity, "intent-filter")
    action = SubElement(intent, "action")
    action.set(f"{NS}name", "android.intent.action.MAIN")
    category = SubElement(intent, "category")
    category.set(f"{NS}name", "android.intent.category.LAUNCHER")
    hidden = SubElement(app, "activity")
    hidden.set(f"{NS}name", "com.example.app.HiddenActivity")
    hidden.set(f"{NS}exported", "false")
    service = SubElement(app, "service")
    service.set(f"{NS}name", ".SyncService")
    service.set(f"{NS}exported", "false")
    service.set(f"{NS}permission", "com.example.CUSTOM")
    return manifest


def _ctx(aapt=None):
    return SimpleNamespace(
        apk=DummyApk(),
        manifest_xml=_manifest(),
        warnings=[],
        aapt=aapt,
    )


def test_manifest_and_sdk() -> None:
    ctx = _ctx()
    manifest = extract_manifest(ctx)
    sdk = extract_sdk(ctx)
    assert manifest["package"] == "com.example.app"
    assert manifest["app_label"] == "Example App"
    assert manifest["version_code"] == 2
    assert manifest["debuggable"] is False
    assert manifest["uses_feature"][0]["name"] == "android.hardware.camera"
    assert sdk["min_sdk"] == 23
    assert sdk["target_sdk"] == 35
    assert sdk["compile_sdk"] is None


def test_permissions_and_metadata() -> None:
    ctx = _ctx()
    permissions = {item["name"]: item for item in extract_permissions(ctx)}
    assert permissions["android.permission.INTERNET"]["protection_level"] == "normal"
    assert permissions["android.permission.INTERNET"]["protection_level_source"] == "aosp_mapping"
    assert permissions["android.permission.CAMERA"]["protection_level"] == "dangerous"
    assert permissions["com.example.CUSTOM"]["protection_level"] == "signature"
    assert permissions["com.example.CUSTOM"]["protection_level_source"] == "manifest"
    metadata = {item["name"]: item for item in extract_metadata(ctx)}
    assert metadata["com.example.CONFIG"] == {"name": "com.example.CONFIG", "value": "prod", "value_type": "string"}
    assert metadata["com.example.FLAG"]["value"] is True
    assert metadata["com.example.COUNT"]["value"] == 7
    assert metadata["com.example.ICON"]["value_type"] == "resource"


def test_activities_and_services() -> None:
    ctx = _ctx()
    activities = extract_activities(ctx, 35)
    services = extract_services(ctx, 35)
    launcher = next(item for item in activities if item["name"].endswith("MainActivity"))
    assert launcher["exported"] is True
    assert launcher["intent_filters"][0]["actions"] == ["android.intent.action.MAIN"]
    hidden = next(item for item in activities if item["name"].endswith("HiddenActivity"))
    assert hidden["exported"] is False
    assert hidden["intent_filters"] == []
    assert services[0]["name"] == "com.example.app.SyncService"
    assert services[0]["permission"] == "com.example.CUSTOM"
    assert services[0]["exported"] is False
