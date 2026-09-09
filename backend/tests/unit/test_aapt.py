from app.modules.apk_analyzer.aapt import parse_badging, prefer
from app.modules.manifest.extract import extract_manifest
from app.modules.permissions.extract import extract_permissions
from app.modules.sdk.extract import extract_sdk
from tests.unit.test_extractors import _ctx

SAMPLE = """
package: name='com.example.app' versionCode='9' versionName='2.0' compileSdkVersion='34' compileSdkVersionCodename='14'
sdkVersion:'24'
targetSdkVersion:'34'
uses-permission: name='android.permission.INTERNET'
uses-permission: name='android.permission.ACCESS_FINE_LOCATION' maxSdkVersion='32'
application-label:'Aapt Label'
"""


def test_parse_badging() -> None:
    parsed = parse_badging(SAMPLE)
    assert parsed["package"] == "com.example.app"
    assert parsed["version_code"] == 9
    assert parsed["version_name"] == "2.0"
    assert parsed["compile_sdk"] == 34
    assert parsed["min_sdk"] == 24
    assert parsed["target_sdk"] == 34
    assert parsed["app_label"] == "Aapt Label"
    perms = {item["name"]: item for item in parsed["permissions"]}
    assert perms["android.permission.ACCESS_FINE_LOCATION"]["max_sdk_version"] == 32


def test_prefer_uses_aapt_and_warns() -> None:
    warnings: list[str] = []
    assert prefer("com.aapt", "com.ag", "package", warnings) == "com.aapt"
    assert warnings
    assert prefer(None, "com.ag", "package", []) == "com.ag"


def test_extractors_prefer_aapt() -> None:
    ctx = _ctx(aapt=parse_badging(SAMPLE))
    manifest = extract_manifest(ctx)
    sdk = extract_sdk(ctx)
    permissions = {item["name"]: item for item in extract_permissions(ctx)}
    assert manifest["package"] == "com.example.app"
    assert manifest["app_label"] == "Aapt Label"
    assert manifest["version_code"] == 9
    assert sdk["min_sdk"] == 24
    assert sdk["target_sdk"] == 34
    assert sdk["compile_sdk"] == 34
    assert "android.permission.ACCESS_FINE_LOCATION" in permissions
    assert any("mismatch" in warning for warning in ctx.warnings)
