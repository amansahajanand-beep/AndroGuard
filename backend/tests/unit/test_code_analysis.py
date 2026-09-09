from types import SimpleNamespace

from app.modules.dex.catalog import match_api, match_sdk
from app.modules.dex.extract import dalvik_to_java, empty_code_analysis, extract_code_analysis, scan_analysis


class FakeClass:
    def __init__(self, name: str, method_count: int = 1):
        self.name = name
        self._method_count = method_count

    def get_nb_methods(self) -> int:
        return self._method_count


class FakeMethod:
    def __init__(self, class_name: str, name: str, descriptor: str, callers: list | None = None):
        self.class_name = class_name
        self.name = name
        self.descriptor = descriptor
        self._callers = callers or []

    def get_class_name(self) -> str:
        return self.class_name

    def get_descriptor(self) -> str:
        return self.descriptor

    def is_external(self) -> bool:
        return True

    def get_xref_from(self):
        return self._callers


class FakeString:
    def __init__(self, value: str, callers: list | None = None):
        self._value = value
        self._callers = callers or []

    def get_value(self) -> str:
        return self._value

    def get_xref_from(self):
        return self._callers


class FakeAnalysis:
    def __init__(self, classes, methods, strings):
        self._classes = classes
        self._methods = methods
        self._strings = strings

    def get_internal_classes(self):
        return self._classes

    def get_external_methods(self):
        return self._methods

    def get_strings(self):
        return self._strings


def _caller(class_name: str, method: str, descriptor: str = "()V"):
    cls = SimpleNamespace(name=class_name)
    meth = SimpleNamespace(name=method, descriptor=descriptor, class_name=class_name)
    return (cls, meth, 0)


def test_dalvik_to_java() -> None:
    assert dalvik_to_java("Lcom/example/app/MainActivity;") == "com.example.app.MainActivity"
    assert dalvik_to_java("") == ""


def test_match_api_and_sdk() -> None:
    telephony = match_api("Landroid/telephony/TelephonyManager;", "getLine1Number")
    assert telephony is not None
    assert telephony.category == "telephony"
    webview = match_api("Landroid/webkit/WebView;", "loadUrl")
    assert webview is not None
    assert webview.category == "webview"
    assert match_api("Lcom/example/Foo;", "bar") is None
    sdk = match_sdk("Lcom/google/android/gms/ads/AdActivity;")
    assert sdk is not None
    assert sdk[1] == "Google AdMob"


def test_scan_analysis_categorizes_call_sites() -> None:
    caller = _caller("Lcom/example/app/CallHelper;", "dial", "(Ljava/lang/String;)V")
    analysis = FakeAnalysis(
        classes=[
            FakeClass("Lcom/example/app/MainActivity;", 4),
            FakeClass("Lcom/google/android/gms/ads/AdView;", 2),
        ],
        methods=[
            FakeMethod(
                "Landroid/telephony/TelephonyManager;",
                "getLine1Number",
                "()Ljava/lang/String;",
                [caller],
            ),
            FakeMethod(
                "Landroid/webkit/WebView;",
                "loadUrl",
                "(Ljava/lang/String;)V",
                [_caller("Lcom/example/app/Browser;", "open")],
            ),
            FakeMethod(
                "Ldalvik/system/DexClassLoader;",
                "<init>",
                "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V",
                [_caller("Lcom/example/app/Loader;", "load")],
            ),
        ],
        strings=[
            FakeString(
                "https://api.example.com/v1/ads",
                [_caller("Lcom/example/app/Net;", "fetch")],
            )
        ],
    )
    result = scan_analysis(
        analysis,
        package="com.example.app",
        permission_names=["android.permission.CALL_PHONE"],
        dex_files=1,
        xref_built=True,
    )
    assert result["summary"]["class_count"] == 2
    assert result["summary"]["dex_files"] == 1
    assert result["classes"][0]["is_app_code"] is True
    assert result["telephony_calls"][0]["api_label"] == "TelephonyManager.getLine1Number"
    assert result["telephony_calls"][0]["caller_class"] == "com.example.app.CallHelper"
    assert result["api_calls"], "confirmed class→method→API mappings are required"
    phone = next(item for item in result["api_calls"] if item["risk_category"] == "PHONE")
    assert phone["class_name"] == "com.example.app.CallHelper"
    assert phone["method_name"] == "dial"
    assert phone["api_class"] == "android.telephony.TelephonyManager"
    assert phone["api_method"] == "getLine1Number"
    assert phone["confidence"] == "HIGH"
    assert "method invocation detected" in phone["evidence"]
    assert phone["is_app_code"] is True
    web = next(item for item in result["api_calls"] if item["api_method"] == "loadUrl")
    assert web["class_name"] == "com.example.app.Browser"
    assert web["api_class"] == "android.webkit.WebView"
    assert result["webview_usage"][0]["api_label"] == "WebView.loadUrl"
    assert result["dynamic_code_loading"][0]["api_label"] == "DexClassLoader.<init>"
    assert result["network_strings"][0]["value"] == "https://api.example.com/v1/ads"
    sdk_names = {item["name"] for item in result["third_party_sdk_usage"]}
    assert "Google AdMob" in sdk_names
    finding_ids = {item["id"] for item in result["code_findings"]}
    assert "TELEPHONY_API_REFERENCED" in finding_ids
    assert "CALL_PHONE_DECLARED_AND_CONFIRMED" in finding_ids
    assert "CONFIRMED_API_CALL_SITES" in finding_ids
    assert "DYNAMIC_CODE_LOADING_REFERENCED" in finding_ids


def test_api_calls_omit_unmapped_sites() -> None:
    analysis = FakeAnalysis(
        classes=[FakeClass("Lcom/example/app/MainActivity;", 1)],
        methods=[
            FakeMethod(
                "Landroid/telecom/TelecomManager;",
                "placeCall",
                "(Landroid/net/Uri;Landroid/os/Bundle;)V",
                [],
            )
        ],
        strings=[],
    )
    result = scan_analysis(analysis, package="com.example.app", dex_files=1, xref_built=True)
    assert result["api_calls"] == []
    assert result["telephony_calls"][0]["confidence"] == "LOW"
    assert result["telephony_calls"][0]["api_class"] == "android.telecom.TelecomManager"
    assert result["telephony_calls"][0]["api_method"] == "placeCall"


def test_empty_code_analysis_shape() -> None:
    payload = empty_code_analysis()
    for key in (
        "classes",
        "methods",
        "api_calls",
        "sensitive_api_calls",
        "network_calls",
        "webview_usage",
        "file_storage_operations",
        "telephony_calls",
        "data_access_indicators",
        "dynamic_code_loading",
        "third_party_sdk_usage",
        "code_findings",
    ):
        assert payload[key] == []


def test_extract_skips_when_no_dex() -> None:
    ctx = SimpleNamespace(
        zip_names=["AndroidManifest.xml", "res/drawable/icon.png"],
        warnings=[],
        job_id="job-1",
        apk=SimpleNamespace(),
        manifest_xml=None,
    )
    result = extract_code_analysis(ctx)
    assert result["summary"]["dex_files"] == 0
    assert result["sensitive_api_calls"] == []
    assert any("No classes.dex" in warning for warning in ctx.warnings)
