"""Build ApplicationIntelligence from existing static APK analysis output.

Reuses AnalysisResponse / analysis data dict — does NOT re-parse the APK.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.apk_intelligence.models import (
    ActivityIntel,
    AdFormatSignal,
    AdSdkSignal,
    AdTriggerHypothesis,
    AdTriggerSignal,
    ApplicationIntelligence,
    DeepLinkSignal,
    FeatureSignal,
    StaticEvidence,
)

logger = logging.getLogger(__name__)

# Known ad SDK name → provider (matched against existing third_party_sdk_usage names).
_AD_SDK_ALIASES: dict[str, tuple[str, str]] = {
    "google admob": ("Google Mobile Ads", "Google"),
    "google mobile ads": ("Google Mobile Ads", "Google"),
    "admob": ("Google Mobile Ads", "Google"),
    "facebook audience network": ("Meta Audience Network", "Meta"),
    "facebook ads": ("Meta Audience Network", "Meta"),
    "ironsource": ("ironSource / LevelPlay", "ironSource"),
    "unity ads": ("Unity Ads", "Unity"),
    "applovin": ("AppLovin", "AppLovin"),
    "vungle": ("Vungle / Liftoff", "Liftoff"),
    "chartboost": ("Chartboost", "Chartboost"),
    "mintegral": ("Mintegral", "Mintegral"),
    "pangle": ("Pangle", "ByteDance"),
}

_AD_FORMAT_CLASS_RX: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"RewardedAd|RewardedInterstitial|RewardedVideo", re.I), "REWARDED", 0.92),
    (re.compile(r"InterstitialAd|Interstitial", re.I), "INTERSTITIAL", 0.85),
    (re.compile(r"AppOpenAd|AppOpen", re.I), "APP_OPEN", 0.88),
    (re.compile(r"NativeAd|NativeAds", re.I), "NATIVE", 0.82),
    (re.compile(r"BannerAd|AdView|BannerView", re.I), "BANNER", 0.80),
]

_AD_TRIGGER_METHOD_RX: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"showRewarded|loadRewarded|showReward", re.I), "REWARDED", 0.84),
    (re.compile(r"showInterstitial|loadInterstitial", re.I), "INTERSTITIAL", 0.82),
    (re.compile(r"showAppOpen|loadAppOpen", re.I), "APP_OPEN", 0.80),
    (re.compile(r"loadAd|showAd|requestAd|initializeAds|MobileAds\.initialize", re.I), "UNKNOWN", 0.55),
]

_FEATURE_PERMISSIONS: dict[str, tuple[str, float]] = {
    "android.permission.CAMERA": ("CAMERA", 0.96),
    "android.permission.RECORD_AUDIO": ("AUDIO", 0.94),
    "android.permission.ACCESS_FINE_LOCATION": ("LOCATION", 0.96),
    "android.permission.ACCESS_COARSE_LOCATION": ("LOCATION", 0.90),
    "android.permission.POST_NOTIFICATIONS": ("NOTIFICATIONS", 0.92),
    "android.permission.READ_CONTACTS": ("CONTACTS", 0.94),
    "android.permission.READ_PHONE_STATE": ("PHONE", 0.88),
    "android.permission.READ_EXTERNAL_STORAGE": ("STORAGE", 0.80),
    "android.permission.WRITE_EXTERNAL_STORAGE": ("STORAGE", 0.80),
    "com.android.vending.BILLING": ("IN_APP_PURCHASE", 0.95),
}

_AUTH_RX = re.compile(r"login|signin|sign_in|auth|otp|register|signup", re.I)
_SETTINGS_RX = re.compile(r"settings|preference|option|config", re.I)
_WEB_RX = re.compile(r"webview|browser|webactivity|chrome", re.I)
_MAIN_RX = re.compile(r"main|home|dashboard|launcher", re.I)
_LAUNCHER = "android.intent.action.MAIN"
_LAUNCHER_CAT = "android.intent.category.LAUNCHER"


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    return value if isinstance(value, dict) else {}


def _analysis_data(analysis: Any) -> dict[str, Any]:
    payload = _as_dict(analysis)
    data = _as_dict(payload.get("data"))
    return data or payload


def build_application_intelligence(analysis: Any) -> ApplicationIntelligence:
    """Normalize existing static analysis into ApplicationIntelligence (once per job)."""
    logger.info("[APK-INTELLIGENCE] Building application intelligence")
    warnings: list[str] = []
    try:
        data = _analysis_data(analysis)
        if not data:
            intel = ApplicationIntelligence(status="empty", warnings=["no_analysis_data"])
            logger.info("[APK-INTELLIGENCE] Intelligence empty (no analysis data)")
            return intel

        apk = _as_dict(data.get("apk"))
        manifest = _as_dict(data.get("manifest"))
        sdk = _as_dict(data.get("sdk"))
        code = _as_dict(data.get("code_analysis"))

        application = {
            "package_name": apk.get("package_name") or manifest.get("package"),
            "version_name": apk.get("version_name") or manifest.get("version_name"),
            "version_code": apk.get("version_code") or manifest.get("version_code"),
            "min_sdk": sdk.get("min_sdk"),
            "target_sdk": sdk.get("target_sdk"),
            "app_label": manifest.get("app_label"),
        }

        activities_raw = data.get("activities") or []
        services_raw = data.get("services") or []
        activities, entry_points, deep_links = _build_activities(activities_raw)
        components = {
            "activity_count": len(activities),
            "service_count": len(services_raw) if isinstance(services_raw, list) else 0,
            "receiver_count": 0,
            "provider_count": 0,
        }

        permissions = _build_permissions(data.get("permissions") or [])
        ui_signals, webview_ok = _build_ui_signals(code)
        if not webview_ok:
            warnings.append("webview_detection_partial")

        libraries, libs_ok = _build_libraries(code)
        if not libs_ok:
            warnings.append("library_detection_partial")

        ads, ads_ok = _build_ads(code, libraries)
        if not ads_ok:
            warnings.append("ad_detection_partial")

        features = _build_features(permissions, ads, ui_signals, code)
        hypotheses = _build_ad_hypotheses(ads)

        signals = {
            "interesting_components": [
                a.name for a in activities if a.launcher or a.exported or a.kind != "UNKNOWN"
            ][:20],
            "navigation_signals": list(entry_points.get("launcher_activities") or [])[:8],
            "risk_signals": [
                f.feature for f in features if f.feature in {"CAMERA", "LOCATION", "PHONE", "CONTACTS"}
            ],
        }

        status = "ready" if not warnings else "partial"
        intel = ApplicationIntelligence(
            status=status,
            application=application,
            components=components,
            permissions=permissions,
            entry_points=entry_points,
            ui_signals=ui_signals,
            libraries=libraries,
            ads=ads,
            features=features,
            signals=signals,
            deep_links=deep_links,
            activities=activities,
            ad_trigger_hypotheses=hypotheses,
            warnings=warnings,
        )
        logger.info(
            "[APK-INTELLIGENCE] Activities=%s services=%s",
            components["activity_count"],
            components["service_count"],
        )
        logger.info(
            "[APK-INTELLIGENCE] WebView detected=%s",
            bool(ui_signals.get("webview_present")),
        )
        logger.info(
            "[APK-INTELLIGENCE] Ad SDK signals=%s",
            len(ads.get("sdk_candidates") or []),
        )
        formats = ads.get("ad_formats") or []
        fmt_bits = []
        for item in formats[:6]:
            if isinstance(item, dict):
                fmt_bits.append(f"{item.get('format')}={item.get('confidence')}")
        if fmt_bits:
            logger.info("[APK-INTELLIGENCE] Ad format signals %s", " ".join(fmt_bits))
        logger.info("[APK-INTELLIGENCE] Features inferred=%s", len(features))
        logger.info("[APK-INTELLIGENCE] Intelligence ready status=%s", status)
        return intel
    except Exception as exc:
        logger.warning("[APK-INTELLIGENCE] Build failed (%s); returning empty", type(exc).__name__)
        return ApplicationIntelligence(
            status="empty",
            warnings=[f"build_failed:{type(exc).__name__}"],
        )


def _build_activities(
    activities_raw: Any,
) -> tuple[list[ActivityIntel], dict[str, Any], list[DeepLinkSignal]]:
    activities: list[ActivityIntel] = []
    launchers: list[str] = []
    exported: list[str] = []
    deep_links: list[DeepLinkSignal] = []

    if not isinstance(activities_raw, list):
        return activities, {
            "launcher_activities": [],
            "exported_activities": [],
            "deep_links": 0,
        }, deep_links

    for raw in activities_raw:
        entry = _as_dict(raw)
        name = str(entry.get("name") or "")
        if not name:
            continue
        filters = entry.get("intent_filters") or []
        is_launcher = False
        for filt in filters:
            f = _as_dict(filt)
            actions = [str(a) for a in (f.get("actions") or [])]
            cats = [str(c) for c in (f.get("categories") or [])]
            if _LAUNCHER in actions and _LAUNCHER_CAT in cats:
                is_launcher = True
            for data_el in f.get("data") or []:
                d = _as_dict(data_el)
                scheme = d.get("scheme")
                host = d.get("host")
                path = d.get("path") or d.get("path_prefix") or d.get("path_pattern")
                if scheme or host:
                    uri = None
                    if scheme:
                        uri = f"{scheme}://"
                        if host:
                            uri += str(host)
                        if path:
                            uri += str(path)
                    deep_links.append(
                        DeepLinkSignal(
                            scheme=scheme,
                            host=host,
                            path=path,
                            activity=name,
                            uri_pattern=uri,
                        )
                    )
        is_exported = bool(entry.get("exported"))
        kind = _classify_activity(name, is_launcher)
        activities.append(
            ActivityIntel(
                name=name,
                exported=is_exported,
                enabled=entry.get("enabled") is not False,
                launcher=is_launcher,
                kind=kind,
                permission=entry.get("permission"),
                intent_filter_count=len(filters) if isinstance(filters, list) else 0,
            )
        )
        if is_launcher:
            launchers.append(name)
        if is_exported:
            exported.append(name)

    entry_points = {
        "launcher_activities": launchers,
        "exported_activities": exported[:40],
        "deep_links": len(deep_links),
    }
    return activities, entry_points, deep_links[:40]


def _classify_activity(name: str, is_launcher: bool) -> str:
    short = name.rsplit(".", 1)[-1]
    if is_launcher:
        return "ENTRY_POINT"
    if _AUTH_RX.search(short):
        return "AUTHENTICATION"
    if _SETTINGS_RX.search(short):
        return "SETTINGS"
    if _WEB_RX.search(short) or _WEB_RX.search(name):
        return "WEB"
    if _MAIN_RX.search(short):
        return "MAIN"
    if "Activity" in short or short:
        return "CONTENT"
    return "UNKNOWN"


def _build_permissions(permissions_raw: Any) -> dict[str, Any]:
    requested: list[str] = []
    dangerous: list[str] = []
    special: list[str] = []
    normal: list[str] = []
    if not isinstance(permissions_raw, list):
        return {
            "requested": [],
            "dangerous": [],
            "special": [],
            "normal": [],
            "unknown": [],
        }
    unknown: list[str] = []
    for raw in permissions_raw:
        entry = _as_dict(raw) if not isinstance(raw, str) else {"name": raw}
        name = str(entry.get("name") or "")
        if not name:
            continue
        requested.append(name)
        level = str(entry.get("protection_level") or entry.get("protection") or "").lower()
        if level == "dangerous":
            dangerous.append(name)
        elif level in {"signature", "signatureorsystem", "privileged", "special"}:
            special.append(name)
        elif level == "normal":
            normal.append(name)
        else:
            # Fall back to AOSP map if present in entry category.
            cat = str(entry.get("category") or "").lower()
            if "dangerous" in cat:
                dangerous.append(name)
            elif "normal" in cat:
                normal.append(name)
            else:
                unknown.append(name)
    return {
        "requested": requested[:120],
        "dangerous": dangerous[:60],
        "special": special[:40],
        "normal": normal[:80],
        "unknown": unknown[:40],
    }


def _build_ui_signals(code: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        webview_usage = code.get("webview_usage") or []
        present = bool(webview_usage)
        evidence: list[dict[str, Any]] = []
        for item in (webview_usage if isinstance(webview_usage, list) else [])[:6]:
            entry = _as_dict(item)
            evidence.append(
                {
                    "source": "code_analysis.webview_usage",
                    "value": str(
                        entry.get("label")
                        or entry.get("api")
                        or entry.get("class")
                        or entry.get("name")
                        or "webview"
                    )[:160],
                    "confidence": 0.95,
                }
            )
        # Also scan class names for WebViewClient / WebChromeClient.
        for raw in (code.get("classes") or [])[:200]:
            entry = _as_dict(raw) if not isinstance(raw, str) else {"name": raw}
            cname = str(entry.get("name") or "")
            if "WebView" in cname or "WebViewClient" in cname or "WebChromeClient" in cname:
                present = True
                evidence.append(
                    {
                        "source": "class",
                        "value": cname[:160],
                        "confidence": 0.90,
                    }
                )
                if len(evidence) >= 8:
                    break
        return {
            "webview_present": present,
            "webview_evidence": evidence[:8],
            "browser_intents": False,
        }, True
    except Exception:
        return {"webview_present": False, "webview_evidence": [], "browser_intents": False}, False


def _build_libraries(code: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    try:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in code.get("third_party_sdk_usage") or []:
            entry = _as_dict(raw) if not isinstance(raw, str) else {"name": raw}
            name = str(entry.get("name") or entry.get("sdk") or entry.get("package") or "")
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            evidence_val = str(entry.get("package") or entry.get("prefix") or name)
            out.append(
                {
                    "name": name,
                    "confidence": 0.92,
                    "evidence": [
                        {
                            "source": "third_party_sdk_usage",
                            "value": evidence_val[:160],
                            "confidence": 0.92,
                        }
                    ],
                }
            )
        return out[:40], True
    except Exception:
        return [], False


def _build_ads(
    code: dict[str, Any],
    libraries: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    try:
        sdk_signals: list[AdSdkSignal] = []
        seen_sdk: set[str] = set()

        # From known third_party SDK names.
        for lib in libraries:
            name = str(lib.get("name") or "")
            key = name.lower()
            for alias, (canonical, provider) in _AD_SDK_ALIASES.items():
                if alias in key:
                    if canonical in seen_sdk:
                        break
                    seen_sdk.add(canonical)
                    ev = [
                        StaticEvidence(
                            source="third_party_sdk_usage",
                            value=name,
                            confidence=0.94,
                        )
                    ]
                    for e in lib.get("evidence") or []:
                        ed = _as_dict(e)
                        if ed.get("value"):
                            ev.append(
                                StaticEvidence(
                                    source=str(ed.get("source") or "sdk"),
                                    value=str(ed["value"]),
                                    confidence=float(ed.get("confidence") or 0.9),
                                )
                            )
                    sdk_signals.append(
                        AdSdkSignal(
                            name=canonical,
                            provider=provider,
                            confidence=0.94,
                            evidence=ev[:6],
                        )
                    )
                    break

        format_signals: dict[str, AdFormatSignal] = {}
        trigger_signals: list[AdTriggerSignal] = []
        related_classes: list[str] = []
        related_methods: list[str] = []

        # Class / method symbol scans (bounded).
        for raw in (code.get("classes") or [])[:400]:
            entry = _as_dict(raw) if not isinstance(raw, str) else {"name": raw}
            cname = str(entry.get("name") or "")
            if not cname:
                continue
            short = cname.rsplit(".", 1)[-1]
            for rx, fmt, conf in _AD_FORMAT_CLASS_RX:
                if rx.search(short) or rx.search(cname):
                    related_classes.append(cname)
                    existing = format_signals.get(fmt)
                    evidence = StaticEvidence(source="class", value=cname, confidence=conf)
                    if existing is None or conf > existing.confidence:
                        format_signals[fmt] = AdFormatSignal(
                            format=fmt,  # type: ignore[arg-type]
                            kind="LIKELY_FORMAT" if conf >= 0.85 else "POSSIBLE_FORMAT",
                            confidence=conf,
                            evidence=[evidence],
                        )
                    elif existing is not None:
                        existing.evidence.append(evidence)

        for raw in (code.get("methods") or [])[:600]:
            entry = _as_dict(raw) if not isinstance(raw, str) else {"name": raw}
            mname = str(entry.get("name") or entry.get("method") or "")
            cname = str(entry.get("class") or entry.get("class_name") or "")
            if not mname:
                continue
            for rx, fmt, conf in _AD_TRIGGER_METHOD_RX:
                if rx.search(mname):
                    related_methods.append(f"{cname}.{mname}" if cname else mname)
                    trigger_signals.append(
                        AdTriggerSignal(
                            type=fmt,  # type: ignore[arg-type]
                            symbol=mname,
                            class_name=cname or None,
                            confidence=conf,
                            evidence="static_symbol_match",
                        )
                    )
                    if fmt != "UNKNOWN":
                        evidence = StaticEvidence(
                            source="method",
                            value=f"{cname}.{mname}" if cname else mname,
                            confidence=conf,
                        )
                        existing = format_signals.get(fmt)
                        if existing is None or conf > existing.confidence:
                            format_signals[fmt] = AdFormatSignal(
                                format=fmt,  # type: ignore[arg-type]
                                kind="POSSIBLE_FORMAT",
                                confidence=conf,
                                evidence=[evidence],
                            )

        # SDK presence also implies possible formats (weaker).
        for sdk in sdk_signals:
            key = sdk.name.lower()
            implied: list[tuple[str, float]] = []
            if "google" in key or "admob" in key:
                implied = [
                    ("BANNER", 0.72),
                    ("INTERSTITIAL", 0.72),
                    ("REWARDED", 0.70),
                    ("NATIVE", 0.65),
                    ("APP_OPEN", 0.60),
                ]
            elif "unity" in key or "ironsource" in key or "applovin" in key or "vungle" in key:
                implied = [("INTERSTITIAL", 0.70), ("REWARDED", 0.72), ("BANNER", 0.65)]
            for fmt, conf in implied:
                if fmt not in format_signals:
                    format_signals[fmt] = AdFormatSignal(
                        format=fmt,  # type: ignore[arg-type]
                        kind="POSSIBLE_FORMAT",
                        confidence=conf,
                        evidence=[
                            StaticEvidence(
                                source="sdk_inference",
                                value=sdk.name,
                                confidence=conf,
                            )
                        ],
                    )

        ads = {
            "sdk_candidates": [s.to_dict() for s in sdk_signals],
            "ad_formats": [f.to_dict() for f in format_signals.values()],
            "ad_related_classes": related_classes[:30],
            "ad_related_methods": related_methods[:30],
            "ad_related_resources": [],
            "ad_triggers": [t.to_dict() for t in trigger_signals[:30]],
            "ad_analysis_status": "READY" if (sdk_signals or format_signals) else "EMPTY",
        }
        return ads, True
    except Exception:
        return {
            "sdk_candidates": [],
            "ad_formats": [],
            "ad_related_classes": [],
            "ad_related_methods": [],
            "ad_related_resources": [],
            "ad_triggers": [],
            "ad_analysis_status": "PARTIAL",
        }, False


def _build_features(
    permissions: dict[str, Any],
    ads: dict[str, Any],
    ui_signals: dict[str, Any],
    code: dict[str, Any],
) -> list[FeatureSignal]:
    features: list[FeatureSignal] = []
    seen: set[str] = set()

    def add(feature: str, confidence: float, evidence: list[str]) -> None:
        if feature in seen:
            return
        seen.add(feature)
        features.append(FeatureSignal(feature=feature, confidence=confidence, evidence=evidence))

    for name in permissions.get("requested") or []:
        mapped = _FEATURE_PERMISSIONS.get(str(name))
        if mapped:
            add(mapped[0], mapped[1], [str(name)])

    if ads.get("sdk_candidates"):
        add("ADS", 0.93, [s.get("name", "ad_sdk") for s in ads["sdk_candidates"][:4]])
    formats = {f.get("format") for f in (ads.get("ad_formats") or []) if isinstance(f, dict)}
    if "REWARDED" in formats:
        add("REWARDED_CONTENT", 0.85, ["static_rewarded_signal"])
    if ui_signals.get("webview_present"):
        add("WEB_CONTENT", 0.90, ["webview_usage"])

    # Billing / IAP from libraries
    for lib in code.get("third_party_sdk_usage") or []:
        entry = _as_dict(lib) if not isinstance(lib, str) else {"name": lib}
        name = str(entry.get("name") or "").lower()
        if "billing" in name or "play billing" in name:
            add("IN_APP_PURCHASE", 0.92, [str(entry.get("name"))])
        if "firebase" in name:
            add("NOTIFICATIONS", 0.55, [str(entry.get("name"))])

    return features


def _build_ad_hypotheses(ads: dict[str, Any]) -> list[AdTriggerHypothesis]:
    out: list[AdTriggerHypothesis] = []
    formats = ads.get("ad_formats") or []
    triggers = ads.get("ad_triggers") or []
    by_fmt: dict[str, list[str]] = {}
    for t in triggers:
        td = _as_dict(t)
        fmt = str(td.get("type") or "UNKNOWN")
        sym = str(td.get("symbol") or "")
        if sym:
            by_fmt.setdefault(fmt, []).append(sym)
    for f in formats:
        fd = _as_dict(f)
        fmt = str(fd.get("format") or "UNKNOWN")
        related = []
        if fmt == "REWARDED":
            related = ["reward", "coins", "video", "watch"]
        elif fmt == "INTERSTITIAL":
            related = ["continue", "next", "play"]
        out.append(
            AdTriggerHypothesis(
                ad_format=fmt,  # type: ignore[arg-type]
                static_symbols=by_fmt.get(fmt, [])[:8]
                or [e.get("value", "") for e in (fd.get("evidence") or [])[:4] if isinstance(e, dict)],
                possible_related_features=related,
                confidence=float(fd.get("confidence") or 0.5),
            )
        )
    return out[:12]
