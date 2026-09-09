"""Static catalogs for DEX API matching. Facts only — no policy scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    class_prefix: str
    method: str | None
    category: str
    label: str
    risk_category: str


CATEGORY_TO_RISK = {
    "telephony": "PHONE",
    "network": "NETWORK",
    "webview": "WEBVIEW",
    "file_storage": "STORAGE",
    "data_access": "DATA_ACCESS",
    "dynamic_code": "DYNAMIC_CODE",
}


def _entry(class_prefix: str, method: str | None, category: str, label: str) -> CatalogEntry:
    return CatalogEntry(
        class_prefix=class_prefix,
        method=method,
        category=category,
        label=label,
        risk_category=CATEGORY_TO_RISK[category],
    )


# Specific method matches. class_prefix is a Dalvik type prefix (Lcom/... or Landroid/...).
API_CATALOG: tuple[CatalogEntry, ...] = (
    # Telephony / SMS / calls
    _entry("Landroid/telephony/TelephonyManager;", "getDeviceId", "telephony", "TelephonyManager.getDeviceId"),
    _entry("Landroid/telephony/TelephonyManager;", "getImei", "telephony", "TelephonyManager.getImei"),
    _entry("Landroid/telephony/TelephonyManager;", "getMeid", "telephony", "TelephonyManager.getMeid"),
    _entry("Landroid/telephony/TelephonyManager;", "getSubscriberId", "telephony", "TelephonyManager.getSubscriberId"),
    _entry("Landroid/telephony/TelephonyManager;", "getLine1Number", "telephony", "TelephonyManager.getLine1Number"),
    _entry("Landroid/telephony/TelephonyManager;", "getSimSerialNumber", "telephony", "TelephonyManager.getSimSerialNumber"),
    _entry("Landroid/telephony/TelephonyManager;", "getNetworkOperator", "telephony", "TelephonyManager.getNetworkOperator"),
    _entry("Landroid/telephony/TelephonyManager;", "listen", "telephony", "TelephonyManager.listen"),
    _entry("Landroid/telephony/SmsManager;", "sendTextMessage", "telephony", "SmsManager.sendTextMessage"),
    _entry("Landroid/telephony/SmsManager;", "sendMultipartTextMessage", "telephony", "SmsManager.sendMultipartTextMessage"),
    _entry("Landroid/telephony/SmsManager;", "sendDataMessage", "telephony", "SmsManager.sendDataMessage"),
    _entry("Landroid/telecom/TelecomManager;", "placeCall", "telephony", "TelecomManager.placeCall"),
    _entry("Landroid/telecom/TelecomManager;", "getLine1Number", "telephony", "TelecomManager.getLine1Number"),
    # Network
    _entry("Ljava/net/HttpURLConnection;", "connect", "network", "HttpURLConnection.connect"),
    _entry("Ljava/net/HttpURLConnection;", "getInputStream", "network", "HttpURLConnection.getInputStream"),
    _entry("Ljava/net/HttpURLConnection;", "getOutputStream", "network", "HttpURLConnection.getOutputStream"),
    _entry("Ljava/net/URL;", "openConnection", "network", "URL.openConnection"),
    _entry("Ljava/net/URL;", "openStream", "network", "URL.openStream"),
    _entry("Ljava/net/Socket;", "connect", "network", "Socket.connect"),
    _entry("Lokhttp3/OkHttpClient;", "newCall", "network", "OkHttpClient.newCall"),
    _entry("Lokhttp3/Call;", "execute", "network", "OkHttp Call.execute"),
    _entry("Lokhttp3/Call;", "enqueue", "network", "OkHttp Call.enqueue"),
    _entry("Lokhttp3/Request$Builder;", "url", "network", "OkHttp Request.Builder.url"),
    _entry("Lretrofit2/Retrofit;", "create", "network", "Retrofit.create"),
    _entry("Ljavax/net/ssl/HttpsURLConnection;", "connect", "network", "HttpsURLConnection.connect"),
    _entry("Lcom/android/volley/RequestQueue;", "add", "network", "Volley RequestQueue.add"),
    # WebView
    _entry("Landroid/webkit/WebView;", "loadUrl", "webview", "WebView.loadUrl"),
    _entry("Landroid/webkit/WebView;", "loadData", "webview", "WebView.loadData"),
    _entry("Landroid/webkit/WebView;", "loadDataWithBaseURL", "webview", "WebView.loadDataWithBaseURL"),
    _entry("Landroid/webkit/WebView;", "evaluateJavascript", "webview", "WebView.evaluateJavascript"),
    _entry("Landroid/webkit/WebView;", "addJavascriptInterface", "webview", "WebView.addJavascriptInterface"),
    _entry("Landroid/webkit/WebView;", "setWebViewClient", "webview", "WebView.setWebViewClient"),
    _entry("Landroid/webkit/WebView;", "setWebChromeClient", "webview", "WebView.setWebChromeClient"),
    _entry("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", "webview", "WebSettings.setJavaScriptEnabled"),
    _entry("Landroid/webkit/WebSettings;", "setAllowFileAccess", "webview", "WebSettings.setAllowFileAccess"),
    _entry("Landroid/webkit/WebSettings;", "setAllowUniversalAccessFromFileURLs", "webview", "WebSettings.setAllowUniversalAccessFromFileURLs"),
    # File / storage
    _entry("Ljava/io/FileOutputStream;", "<init>", "file_storage", "FileOutputStream.<init>"),
    _entry("Ljava/io/FileInputStream;", "<init>", "file_storage", "FileInputStream.<init>"),
    _entry("Ljava/io/FileWriter;", "<init>", "file_storage", "FileWriter.<init>"),
    _entry("Landroid/content/Context;", "openFileOutput", "file_storage", "Context.openFileOutput"),
    _entry("Landroid/content/Context;", "openFileInput", "file_storage", "Context.openFileInput"),
    _entry("Landroid/content/Context;", "getSharedPreferences", "file_storage", "Context.getSharedPreferences"),
    _entry("Landroid/content/Context;", "getExternalFilesDir", "file_storage", "Context.getExternalFilesDir"),
    _entry("Landroid/os/Environment;", "getExternalStorageDirectory", "file_storage", "Environment.getExternalStorageDirectory"),
    _entry("Landroid/os/Environment;", "getExternalStoragePublicDirectory", "file_storage", "Environment.getExternalStoragePublicDirectory"),
    _entry("Landroid/database/sqlite/SQLiteDatabase;", "openOrCreateDatabase", "file_storage", "SQLiteDatabase.openOrCreateDatabase"),
    _entry("Landroid/database/sqlite/SQLiteDatabase;", "execSQL", "file_storage", "SQLiteDatabase.execSQL"),
    _entry("Landroid/database/sqlite/SQLiteDatabase;", "insert", "file_storage", "SQLiteDatabase.insert"),
    _entry("Landroid/database/sqlite/SQLiteDatabase;", "query", "file_storage", "SQLiteDatabase.query"),
    _entry("Landroidx/security/crypto/EncryptedSharedPreferences;", "create", "file_storage", "EncryptedSharedPreferences.create"),
    # Data access / identifiers
    _entry("Landroid/location/LocationManager;", "getLastKnownLocation", "data_access", "LocationManager.getLastKnownLocation"),
    _entry("Landroid/location/LocationManager;", "requestLocationUpdates", "data_access", "LocationManager.requestLocationUpdates"),
    _entry("Lcom/google/android/gms/location/FusedLocationProviderClient;", "getLastLocation", "data_access", "FusedLocationProviderClient.getLastLocation"),
    _entry("Landroid/accounts/AccountManager;", "getAccounts", "data_access", "AccountManager.getAccounts"),
    _entry("Landroid/accounts/AccountManager;", "getAccountsByType", "data_access", "AccountManager.getAccountsByType"),
    _entry("Landroid/provider/Settings$Secure;", "getString", "data_access", "Settings.Secure.getString"),
    _entry("Landroid/content/ContentResolver;", "query", "data_access", "ContentResolver.query"),
    _entry("Landroid/content/ContentResolver;", "insert", "data_access", "ContentResolver.insert"),
    _entry("Landroid/provider/ContactsContract$Contacts;", "query", "data_access", "ContactsContract.query"),
    _entry("Landroid/media/MediaRecorder;", "start", "data_access", "MediaRecorder.start"),
    _entry("Landroid/hardware/Camera;", "open", "data_access", "Camera.open"),
    _entry("Landroid/hardware/camera2/CameraManager;", "openCamera", "data_access", "CameraManager.openCamera"),
    _entry("Landroid/media/AudioRecord;", "startRecording", "data_access", "AudioRecord.startRecording"),
    _entry("Landroid/content/ClipboardManager;", "getPrimaryClip", "data_access", "ClipboardManager.getPrimaryClip"),
    _entry("Landroid/content/pm/PackageManager;", "getInstalledPackages", "data_access", "PackageManager.getInstalledPackages"),
    _entry("Landroid/content/pm/PackageManager;", "getInstalledApplications", "data_access", "PackageManager.getInstalledApplications"),
    _entry("Lcom/google/android/gms/ads/identifier/AdvertisingIdClient;", "getAdvertisingIdInfo", "data_access", "AdvertisingIdClient.getAdvertisingIdInfo"),
    _entry("Landroid/telephony/TelephonyManager;", "getAllCellInfo", "data_access", "TelephonyManager.getAllCellInfo"),
    _entry("Landroid/net/wifi/WifiInfo;", "getMacAddress", "data_access", "WifiInfo.getMacAddress"),
    _entry("Landroid/provider/CallLog$Calls;", "CONTENT_URI", "data_access", "CallLog.Calls.CONTENT_URI"),
    # Dynamic code loading / reflection / native
    _entry("Ldalvik/system/DexClassLoader;", "<init>", "dynamic_code", "DexClassLoader.<init>"),
    _entry("Ldalvik/system/PathClassLoader;", "<init>", "dynamic_code", "PathClassLoader.<init>"),
    _entry("Ldalvik/system/InMemoryDexClassLoader;", "<init>", "dynamic_code", "InMemoryDexClassLoader.<init>"),
    _entry("Ljava/lang/Runtime;", "exec", "dynamic_code", "Runtime.exec"),
    _entry("Ljava/lang/Runtime;", "load", "dynamic_code", "Runtime.load"),
    _entry("Ljava/lang/Runtime;", "loadLibrary", "dynamic_code", "Runtime.loadLibrary"),
    _entry("Ljava/lang/System;", "load", "dynamic_code", "System.load"),
    _entry("Ljava/lang/System;", "loadLibrary", "dynamic_code", "System.loadLibrary"),
    _entry("Ljava/lang/Class;", "forName", "dynamic_code", "Class.forName"),
    _entry("Ljava/lang/ClassLoader;", "loadClass", "dynamic_code", "ClassLoader.loadClass"),
    _entry("Ljava/lang/reflect/Method;", "invoke", "dynamic_code", "Method.invoke"),
    _entry("Ljavax/script/ScriptEngine;", "eval", "dynamic_code", "ScriptEngine.eval"),
    _entry("Landroid/content/Context;", "createPackageContext", "dynamic_code", "Context.createPackageContext"),
)

# Class-prefix matches for any method on that type (used sparingly).
CLASS_ANY_METHOD: tuple[CatalogEntry, ...] = (
    _entry("Ldalvik/system/DexClassLoader;", None, "dynamic_code", "DexClassLoader"),
    _entry("Ldalvik/system/InMemoryDexClassLoader;", None, "dynamic_code", "InMemoryDexClassLoader"),
    _entry("Landroid/webkit/WebView;", None, "webview", "WebView"),
    _entry("Landroid/telephony/SmsManager;", None, "telephony", "SmsManager"),
)

SDK_PACKAGES: tuple[tuple[str, str], ...] = (
    ("Lcom/google/android/gms/ads/", "Google AdMob"),
    ("Lcom/google/android/gms/maps/", "Google Maps"),
    ("Lcom/google/android/gms/location/", "Google Play Location"),
    ("Lcom/google/android/gms/measurement/", "Google Analytics / Measurement"),
    ("Lcom/google/firebase/", "Firebase"),
    ("Lcom/facebook/ads/", "Facebook Audience Network"),
    ("Lcom/facebook/", "Facebook SDK"),
    ("Lcom/appsflyer/", "AppsFlyer"),
    ("Lcom/adjust/", "Adjust"),
    ("Lio/branch/", "Branch"),
    ("Lcom/ironsource/", "ironSource"),
    ("Lcom/unity3d/ads/", "Unity Ads"),
    ("Lcom/applovin/", "AppLovin"),
    ("Lcom/vungle/", "Vungle"),
    ("Lcom/chartboost/", "Chartboost"),
    ("Lcom/android/billingclient/", "Play Billing"),
    ("Lcom/google/android/play/core/integrity/", "Play Integrity"),
    ("Lcom/pairip/", "Google Play PairIP"),
    ("Lokhttp3/", "OkHttp"),
    ("Lretrofit2/", "Retrofit"),
    ("Lcom/android/volley/", "Volley"),
    ("Lcom/bumptech/glide/", "Glide"),
)


def _index_by_method() -> dict[str, tuple[CatalogEntry, ...]]:
    buckets: dict[str, list[CatalogEntry]] = {}
    for entry in API_CATALOG:
        if entry.method is None:
            continue
        buckets.setdefault(entry.method, []).append(entry)
    return {name: tuple(items) for name, items in buckets.items()}


BY_METHOD = _index_by_method()


def match_api(class_name: str, method_name: str) -> CatalogEntry | None:
    """Return the first catalog match for a Dalvik class + method, or None."""
    for entry in BY_METHOD.get(method_name, ()):
        if class_name.startswith(entry.class_prefix):
            return entry
    for entry in CLASS_ANY_METHOD:
        if class_name.startswith(entry.class_prefix):
            return entry
    return None


def match_sdk(dalvik_class: str) -> tuple[str, str] | None:
    for prefix, name in SDK_PACKAGES:
        if dalvik_class.startswith(prefix):
            return prefix, name
    return None


def dalvik_type_to_java(dalvik_name: str | None) -> str:
    if not dalvik_name:
        return ""
    text = str(dalvik_name)
    if text.startswith("L") and text.endswith(";"):
        return text[1:-1].replace("/", ".")
    if text.startswith("L") and "/" in text:
        return text[1:].rstrip(";").replace("/", ".")
    return text.replace("/", ".")


def api_class_name(dalvik_class: str, entry: CatalogEntry) -> str:
    """Prefer the catalog class_prefix type; fall back to the matched Dalvik class."""
    prefix = entry.class_prefix
    if prefix.endswith(";"):
        return dalvik_type_to_java(prefix)
    return dalvik_type_to_java(dalvik_class)


def api_method_name(method_name: str, entry: CatalogEntry) -> str:
    return entry.method or method_name or entry.label.split(".")[-1]
