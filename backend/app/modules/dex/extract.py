from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from app.core.config import settings
from app.modules.apk_analyzer.context import ApkContext
from app.modules.dex.catalog import api_class_name, api_method_name, match_api, match_sdk

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\"'<>\\]{4,256}", re.IGNORECASE)
_HOST_HINT_RE = re.compile(
    r"(?:(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|app|me|info|biz|dev)(?:/[^\s\"']*)?)",
    re.IGNORECASE,
)
_PAIRIP_MARKERS = ("pairip", "libpairip", "com.pairip")
_SKIP_CLASS_PREFIXES = (
    "Landroid/",
    "Landroidx/",
    "Lcom/google/android/",
    "Lcom/google/firebase/",
    "Lkotlin/",
    "Lkotlinx/",
    "Ljava/",
    "Ljavax/",
    "Lokhttp3/",
    "Lokio/",
    "Lretrofit2/",
)

CATEGORY_BUCKETS = {
    "telephony": "telephony_calls",
    "network": "network_calls",
    "webview": "webview_usage",
    "file_storage": "file_storage_operations",
    "data_access": "data_access_indicators",
    "dynamic_code": "dynamic_code_loading",
}


def empty_code_analysis(**overrides: Any) -> dict:
    payload = {
        "summary": {
            "dex_files": 0,
            "class_count": 0,
            "method_count": 0,
            "xref_built": False,
            "truncated": False,
        },
        "classes": [],
        "methods": [],
        "sensitive_api_calls": [],
        "api_calls": [],
        "network_calls": [],
        "webview_usage": [],
        "file_storage_operations": [],
        "telephony_calls": [],
        "data_access_indicators": [],
        "dynamic_code_loading": [],
        "third_party_sdk_usage": [],
        "network_strings": [],
        "code_findings": [],
    }
    payload.update(overrides)
    return payload


def dalvik_to_java(name: str | None) -> str:
    if not name:
        return ""
    text = str(name)
    if text.startswith("L") and text.endswith(";"):
        return text[1:-1].replace("/", ".")
    return text.replace("/", ".")


def _is_app_class(dalvik_name: str, package: str) -> bool:
    if not package:
        return False
    java = dalvik_to_java(dalvik_name)
    return java == package or java.startswith(package + ".")


def _caller_from_xref(item: Any) -> tuple[str, str, str | None, int | None]:
    offset: int | None = None
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        cls, meth = item[0], item[1]
        if len(item) >= 3 and isinstance(item[2], int):
            offset = item[2]
    else:
        return "", "", None, None
    class_name = dalvik_to_java(getattr(cls, "name", None) or getattr(meth, "class_name", None))
    method_name = getattr(meth, "name", None) or ""
    descriptor = getattr(meth, "descriptor", None)
    if descriptor is None and hasattr(meth, "get_descriptor"):
        try:
            descriptor = meth.get_descriptor()
        except Exception:
            descriptor = None
    return (
        class_name,
        method_name,
        str(descriptor) if descriptor is not None else None,
        offset,
    )


def _format_method_signature(method_name: str, descriptor: str | None) -> str:
    if descriptor:
        return f"{method_name}{descriptor}"
    return f"{method_name}()"


def _build_mapped_call(
    *,
    caller_class: str,
    caller_method: str,
    caller_descriptor: str | None,
    api_dalvik_class: str,
    api_method: str,
    entry: Any,
    offset: int | None,
    package: str,
) -> dict:
    api_cls = api_class_name(api_dalvik_class, entry)
    api_meth = api_method_name(api_method, entry)
    evidence = "method invocation detected"
    if offset is not None:
        evidence = f"method invocation detected at bytecode offset 0x{offset:x}"
    is_app = bool(package and caller_class and (caller_class == package or caller_class.startswith(package + ".")))
    return {
        "class_name": caller_class,
        "method_name": caller_method,
        "method_signature": _format_method_signature(caller_method, caller_descriptor),
        "api_class": api_cls,
        "api_method": api_meth,
        "api": f"{api_cls}.{api_meth}",
        "risk_category": entry.risk_category,
        "category": entry.category,
        "evidence": evidence,
        "confidence": "HIGH",
        "is_app_code": is_app,
    }


def _cap(items: list, limit: int) -> tuple[list, bool]:
    if len(items) <= limit:
        return items, False
    return items[:limit], True


def _looks_protected(ctx: ApkContext) -> bool:
    names = " ".join(ctx.zip_names).lower()
    if any(marker in names for marker in _PAIRIP_MARKERS):
        return True
    if ctx.manifest_xml is None:
        return False
    from app.core.xmlutil import android_attr, find_application

    app = find_application(ctx.manifest_xml)
    app_class = android_attr(app, "name") if app is not None else ""
    return "pairip" in (app_class or "").lower()


def _load_dex_types():
    try:
        from androguard.core.dex import DEX
    except ImportError:  # pragma: no cover
        from androguard.core.bytecodes.dvm import DalvikVMFormat as DEX
    from androguard.core.analysis.analysis import Analysis

    return DEX, Analysis


def _quiet_androguard() -> None:
    logging.getLogger("androguard").setLevel(logging.ERROR)
    try:
        from loguru import logger as loguru_logger

        loguru_logger.disable("androguard")
    except Exception:
        pass


def _build_analysis(ctx: ApkContext) -> tuple[Any, int, bool] | None:
    dex_names = [name for name in ctx.zip_names if re.fullmatch(r"classes(\d*)\.dex", name or "")]
    if not dex_names:
        ctx.warnings.append("No classes.dex found; DEX code analysis was skipped.")
        return None

    DEX, Analysis = _load_dex_types()
    _quiet_androguard()
    analysis = Analysis()
    loaded = 0
    try:
        for blob in ctx.apk.get_all_dex():
            if not blob:
                continue
            analysis.add(DEX(blob))
            loaded += 1
    except Exception:
        logger.warning("Failed to parse DEX for job %s", ctx.job_id, exc_info=True)
        ctx.warnings.append("One or more DEX files could not be parsed.")
        if loaded == 0:
            return None

    xref_built = False
    try:
        analysis.create_xref()
        xref_built = True
    except Exception:
        logger.warning("DEX xref build failed for job %s", ctx.job_id, exc_info=True)
        ctx.warnings.append("DEX cross-references could not be built; API call sites may be incomplete.")
    return analysis, loaded, xref_built


def _scan_strings(analysis: Any, limit: int) -> tuple[list[dict], bool]:
    results: list[dict] = []
    truncated = False
    for item in analysis.get_strings() or []:
        if len(results) >= limit:
            truncated = True
            break
        try:
            value = item.get_value() if hasattr(item, "get_value") else str(item)
        except Exception:
            continue
        if not value or len(value) < 8:
            continue
        url_match = _URL_RE.search(value)
        host_match = None if url_match else _HOST_HINT_RE.search(value)
        if not url_match and not host_match:
            continue
        kind = "url" if url_match else "host"
        extracted = (url_match.group(0) if url_match else host_match.group(0)).rstrip(").,;")
        caller_class = caller_method = None
        try:
            xrefs = list(item.get_xref_from() or [])
        except Exception:
            xrefs = []
        if xrefs:
            caller_class, caller_method, _, _ = _caller_from_xref(next(iter(xrefs)))
        results.append(
            {
                "value": extracted[:256],
                "kind": kind,
                "caller_class": caller_class or None,
                "caller_method": caller_method or None,
            }
        )
    return results, truncated


def scan_analysis(
    analysis: Any,
    *,
    package: str = "",
    permission_names: list[str] | None = None,
    dex_files: int = 0,
    xref_built: bool = True,
    protected: bool = False,
    max_classes: int | None = None,
    max_methods: int | None = None,
    max_findings: int | None = None,
) -> dict:
    max_classes = max_classes if max_classes is not None else settings.max_code_classes
    max_methods = max_methods if max_methods is not None else settings.max_code_methods
    max_findings = max_findings if max_findings is not None else settings.max_code_findings
    permission_names = permission_names or []

    class_count = 0
    method_count = 0
    app_classes: list[dict] = []
    other_classes: list[dict] = []
    sdk_hits: dict[str, dict] = {}

    for cls in analysis.get_internal_classes() or []:
        class_count += 1
        dalvik_name = getattr(cls, "name", "") or ""
        try:
            n_methods = cls.get_nb_methods() if hasattr(cls, "get_nb_methods") else len(list(cls.get_methods()))
        except Exception:
            n_methods = 0
        method_count += n_methods
        java_name = dalvik_to_java(dalvik_name)
        record = {
            "name": java_name,
            "dalvik_name": dalvik_name,
            "method_count": n_methods,
            "is_app_code": _is_app_class(dalvik_name, package),
        }
        if record["is_app_code"]:
            app_classes.append(record)
        elif not any(dalvik_name.startswith(prefix) for prefix in _SKIP_CLASS_PREFIXES):
            other_classes.append(record)

        sdk = match_sdk(dalvik_name)
        if sdk:
            prefix, sdk_name = sdk
            bucket = sdk_hits.setdefault(
                sdk_name,
                {
                    "name": sdk_name,
                    "package_prefix": prefix[1:].rstrip("/").replace("/", "."),
                    "class_count": 0,
                    "sample_classes": [],
                },
            )
            bucket["class_count"] += 1
            if java_name not in bucket["sample_classes"] and len(bucket["sample_classes"]) < 5:
                bucket["sample_classes"].append(java_name)

    listed_classes = app_classes + other_classes
    listed_classes, classes_truncated = _cap(listed_classes, max_classes)

    buckets: dict[str, list[dict]] = {key: [] for key in CATEGORY_BUCKETS.values()}
    sensitive: list[dict] = []
    api_calls: list[dict] = []
    method_map: dict[tuple[str, str, str | None], set[str]] = defaultdict(set)
    seen_calls: set[tuple[str, str, str, str]] = set()
    seen_mapped: set[tuple[str, str, str, str, str]] = set()
    per_category_cap = max(20, max_findings // 6)
    findings_truncated = False

    for meth in analysis.get_external_methods() or []:
        class_name = getattr(meth, "class_name", "") or meth.get_class_name()
        method_name = getattr(meth, "name", "") or ""
        descriptor = getattr(meth, "descriptor", None)
        if descriptor is None and hasattr(meth, "get_descriptor"):
            descriptor = meth.get_descriptor()
        entry = match_api(class_name, method_name)
        if entry is None:
            continue
        bucket_name = CATEGORY_BUCKETS[entry.category]
        if len(buckets[bucket_name]) >= per_category_cap and len(api_calls) >= max_findings:
            findings_truncated = True
            continue
        try:
            xrefs = list(meth.get_xref_from() or [])
        except Exception:
            xrefs = []
        api = f"{class_name}->{method_name}{descriptor or ''}"
        api_cls = api_class_name(class_name, entry)
        api_meth = api_method_name(method_name, entry)

        if not xrefs:
            # API exists in DEX but no call-site xref — keep as unconfirmed indicator only.
            if len(buckets[bucket_name]) < per_category_cap:
                call = {
                    "api": api,
                    "api_label": entry.label,
                    "api_class": api_cls,
                    "api_method": api_meth,
                    "category": entry.category,
                    "risk_category": entry.risk_category,
                    "caller_class": None,
                    "caller_method": None,
                    "caller_descriptor": None,
                    "confidence": "LOW",
                    "evidence": "API referenced in DEX without a resolved call site",
                }
                buckets[bucket_name].append(call)
                sensitive.append(call)
            continue

        for xref in xrefs:
            if len(buckets[bucket_name]) >= per_category_cap and len(api_calls) >= max_findings:
                findings_truncated = True
                break
            caller_class, caller_method, caller_desc, offset = _caller_from_xref(xref)
            if not caller_class or not caller_method:
                continue
            dedupe_key = (api, caller_class, caller_method, caller_desc or "")
            if dedupe_key in seen_calls:
                continue
            seen_calls.add(dedupe_key)
            call = {
                "api": api,
                "api_label": entry.label,
                "api_class": api_cls,
                "api_method": api_meth,
                "category": entry.category,
                "risk_category": entry.risk_category,
                "caller_class": caller_class,
                "caller_method": caller_method,
                "caller_descriptor": caller_desc,
                "confidence": "HIGH",
                "evidence": (
                    f"method invocation detected at bytecode offset 0x{offset:x}"
                    if offset is not None
                    else "method invocation detected"
                ),
            }
            if len(buckets[bucket_name]) < per_category_cap:
                buckets[bucket_name].append(call)
                sensitive.append(call)
            method_map[(caller_class, caller_method, caller_desc)].add(entry.label)

            mapped_key = (caller_class, caller_method, api_cls, api_meth, entry.risk_category)
            if mapped_key in seen_mapped:
                continue
            seen_mapped.add(mapped_key)
            if len(api_calls) < max_findings:
                api_calls.append(
                    _build_mapped_call(
                        caller_class=caller_class,
                        caller_method=caller_method,
                        caller_descriptor=caller_desc,
                        api_dalvik_class=class_name,
                        api_method=method_name,
                        entry=entry,
                        offset=offset,
                        package=package,
                    )
                )
            else:
                findings_truncated = True

    # Prefer app-package call sites first for LLM/audit consumers.
    api_calls.sort(
        key=lambda item: (
            0 if item.get("is_app_code") else 1,
            item.get("risk_category") or "",
            item.get("class_name") or "",
            item.get("method_name") or "",
            item.get("api") or "",
        )
    )

    methods: list[dict] = []
    for (cls_name, meth_name, desc), labels in method_map.items():
        if not cls_name or not meth_name:
            continue
        methods.append(
            {
                "class_name": cls_name,
                "name": meth_name,
                "descriptor": desc,
                "api_labels": sorted(labels),
            }
        )
    methods, methods_truncated = _cap(methods, max_methods)

    network_strings, strings_truncated = _scan_strings(analysis, max_findings)
    sdk_list = sorted(sdk_hits.values(), key=lambda item: (-item["class_count"], item["name"]))

    truncated = classes_truncated or methods_truncated or findings_truncated or strings_truncated
    findings = _build_findings(
        buckets=buckets,
        api_calls=api_calls,
        sdk_list=sdk_list,
        network_strings=network_strings,
        permission_names=permission_names,
        protected=protected,
        xref_built=xref_built,
    )

    return {
        "summary": {
            "dex_files": dex_files,
            "class_count": class_count,
            "method_count": method_count,
            "xref_built": xref_built,
            "truncated": truncated,
        },
        "classes": listed_classes,
        "methods": methods,
        "api_calls": api_calls,
        "sensitive_api_calls": sensitive,
        "network_calls": buckets["network_calls"],
        "webview_usage": buckets["webview_usage"],
        "file_storage_operations": buckets["file_storage_operations"],
        "telephony_calls": buckets["telephony_calls"],
        "data_access_indicators": buckets["data_access_indicators"],
        "dynamic_code_loading": buckets["dynamic_code_loading"],
        "third_party_sdk_usage": sdk_list,
        "network_strings": network_strings,
        "code_findings": findings,
    }


def _build_findings(
    *,
    buckets: dict[str, list[dict]],
    api_calls: list[dict] | None = None,
    sdk_list: list[dict],
    network_strings: list[dict],
    permission_names: list[str],
    protected: bool,
    xref_built: bool,
) -> list[dict]:
    findings: list[dict] = []
    api_calls = api_calls or []

    def add(finding_id: str, category: str, title: str, detail: str, evidence: list[str]) -> None:
        findings.append(
            {
                "id": finding_id,
                "category": category,
                "title": title,
                "detail": detail,
                "evidence": evidence[:12],
            }
        )

    mapping = [
        ("telephony_calls", "TELEPHONY_API_REFERENCED", "telephony", "Telephony APIs are referenced in DEX"),
        ("network_calls", "NETWORK_API_REFERENCED", "network", "Network APIs are referenced in DEX"),
        ("webview_usage", "WEBVIEW_API_REFERENCED", "webview", "WebView APIs are referenced in DEX"),
        ("file_storage_operations", "FILE_STORAGE_API_REFERENCED", "file_storage", "File/storage APIs are referenced in DEX"),
        ("data_access_indicators", "DATA_ACCESS_API_REFERENCED", "data_access", "Identifier or data-access APIs are referenced in DEX"),
        ("dynamic_code_loading", "DYNAMIC_CODE_LOADING_REFERENCED", "dynamic_code", "Dynamic code loading or reflection APIs are referenced in DEX"),
    ]
    for key, finding_id, category, title in mapping:
        calls = buckets.get(key) or []
        if not calls:
            continue
        labels = []
        for call in calls:
            label = call.get("api_label") or call.get("api")
            if label and label not in labels:
                labels.append(label)
        add(
            finding_id,
            category,
            title,
            f"Static analysis found {len(calls)} call site(s) and {len(labels)} unique API(s).",
            labels,
        )

    if api_calls:
        add(
            "CONFIRMED_API_CALL_SITES",
            "code",
            "Confirmed class→method→API call sites were mapped",
            f"{len(api_calls)} HIGH-confidence invocation(s) with caller class and method.",
            [
                f"{item['class_name']}.{item['method_name']} → {item['api']}"
                for item in api_calls[:12]
            ],
        )

    if sdk_list:
        add(
            "THIRD_PARTY_SDK_PRESENT",
            "sdk",
            "Third-party SDK classes are present in DEX",
            f"{len(sdk_list)} SDK package prefix(es) matched internal class names.",
            [item["name"] for item in sdk_list],
        )
    if network_strings:
        add(
            "URL_STRINGS_PRESENT",
            "network",
            "URL or host strings are present in DEX",
            f"{len(network_strings)} HTTP(S) URL or host-like string(s) were found.",
            [item["value"] for item in network_strings[:12]],
        )

    declared = set(permission_names)
    phone_mapped = [
        item
        for item in api_calls
        if item.get("risk_category") == "PHONE"
    ]
    if "android.permission.CALL_PHONE" in declared and phone_mapped:
        add(
            "CALL_PHONE_DECLARED_AND_CONFIRMED",
            "telephony",
            "CALL_PHONE is declared and phone APIs have confirmed call sites",
            "Use code_analysis.api_calls for class/method evidence. Mark Confirmed only when mapped.",
            [
                f"{item['class_name']}.{item['method_name']} → {item['api']}"
                for item in phone_mapped[:8]
            ],
        )
    elif "android.permission.CALL_PHONE" in declared and buckets.get("telephony_calls"):
        add(
            "CALL_PHONE_DECLARED_AND_REFERENCED",
            "telephony",
            "CALL_PHONE is declared and telephony APIs are referenced",
            "Manifest requests CALL_PHONE and DEX contains telephony API references; call-site mapping may be incomplete.",
            ["android.permission.CALL_PHONE"],
        )
    if "android.permission.SYSTEM_ALERT_WINDOW" in declared:
        add(
            "SYSTEM_ALERT_WINDOW_DECLARED",
            "overlay",
            "SYSTEM_ALERT_WINDOW is declared in the manifest",
            "The permission is present in the manifest. This is not proof of overlay use at runtime.",
            ["android.permission.SYSTEM_ALERT_WINDOW"],
        )
    if protected:
        add(
            "PAIRIP_PROTECTION_DETECTED",
            "integrity",
            "Play PairIP / runtime protection markers were found",
            "Static DEX analysis may miss code that is decrypted or loaded only at runtime.",
            ["com.pairip"],
        )
    if not xref_built:
        add(
            "DEX_XREF_INCOMPLETE",
            "analysis",
            "DEX cross-references were not fully built",
            "API call-site lists may be incomplete.",
            [],
        )
    return findings


def extract_code_analysis(ctx: ApkContext, permission_names: list[str] | None = None) -> dict:
    if not settings.dex_analysis_enabled:
        ctx.warnings.append("DEX code analysis is disabled.")
        return empty_code_analysis()

    built = _build_analysis(ctx)
    if built is None:
        result = empty_code_analysis()
        if _looks_protected(ctx):
            result["code_findings"] = _build_findings(
                buckets={key: [] for key in CATEGORY_BUCKETS.values()},
                sdk_list=[],
                network_strings=[],
                permission_names=permission_names or [],
                protected=True,
                xref_built=False,
            )
        return result

    analysis, dex_files, xref_built = built
    try:
        package = ctx.apk.get_package() or ""
    except Exception:
        package = ""
    try:
        result = scan_analysis(
            analysis,
            package=package,
            permission_names=permission_names or [],
            dex_files=dex_files,
            xref_built=xref_built,
            protected=_looks_protected(ctx),
        )
    except Exception:
        logger.exception("DEX scan failed for job %s", ctx.job_id)
        ctx.warnings.append("DEX code analysis failed; code_analysis is incomplete.")
        return empty_code_analysis(
            summary={
                "dex_files": dex_files,
                "class_count": 0,
                "method_count": 0,
                "xref_built": xref_built,
                "truncated": False,
            }
        )

    if result["summary"]["truncated"]:
        ctx.warnings.append("DEX code analysis lists were truncated at the configured maximum.")
    return result
