"""Phase 12F — Application Intelligence models (static evidence only).

Does not execute APK code, ADB, shell, or invent runtime confirmations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AdFormat = Literal[
    "BANNER",
    "INTERSTITIAL",
    "REWARDED",
    "NATIVE",
    "APP_OPEN",
    "UNKNOWN",
]

SignalKind = Literal["STATIC_SIGNAL", "POSSIBLE_FORMAT", "LIKELY_FORMAT"]

ActivityKind = Literal[
    "ENTRY_POINT",
    "AUTHENTICATION",
    "MAIN",
    "SETTINGS",
    "CONTENT",
    "WEB",
    "UNKNOWN",
]


@dataclass
class StaticEvidence:
    source: str
    value: str
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "value": self.value[:240],
            "confidence": _clamp(self.confidence),
        }


@dataclass
class AdSdkSignal:
    name: str
    provider: str
    confidence: float
    evidence: list[StaticEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "confidence": _clamp(self.confidence),
            "evidence": [e.to_dict() for e in self.evidence[:8]],
        }


@dataclass
class AdFormatSignal:
    format: AdFormat
    kind: SignalKind = "STATIC_SIGNAL"
    confidence: float = 0.5
    evidence: list[StaticEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "kind": self.kind,
            "confidence": _clamp(self.confidence),
            "evidence": [e.to_dict() for e in self.evidence[:8]],
        }


@dataclass
class AdTriggerSignal:
    """Hypothesis only — never executed."""

    type: AdFormat
    symbol: str
    class_name: str | None = None
    confidence: float = 0.5
    evidence: str = "static_symbol_match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "symbol": self.symbol[:120],
            "class": self.class_name,
            "confidence": _clamp(self.confidence),
            "evidence": self.evidence,
        }


@dataclass
class AdTriggerHypothesis:
    ad_format: AdFormat
    static_symbols: list[str] = field(default_factory=list)
    possible_related_features: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "ad_format": self.ad_format,
            "static_symbols": list(self.static_symbols)[:12],
            "possible_related_features": list(self.possible_related_features)[:12],
            "confidence": _clamp(self.confidence),
        }


@dataclass
class FeatureSignal:
    feature: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "confidence": _clamp(self.confidence),
            "evidence": list(self.evidence)[:8],
        }


@dataclass
class DeepLinkSignal:
    scheme: str | None = None
    host: str | None = None
    path: str | None = None
    activity: str | None = None
    uri_pattern: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "host": self.host,
            "path": self.path,
            "activity": self.activity,
            "uri_pattern": self.uri_pattern,
        }


@dataclass
class ActivityIntel:
    name: str
    exported: bool = False
    enabled: bool = True
    launcher: bool = False
    kind: ActivityKind = "UNKNOWN"
    permission: str | None = None
    intent_filter_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "exported": self.exported,
            "enabled": self.enabled,
            "launcher": self.launcher,
            "kind": self.kind,
            "permission": self.permission,
            "intent_filter_count": self.intent_filter_count,
        }


@dataclass
class ApplicationIntelligence:
    """Normalized static APK intelligence for AgentState / AI context."""

    status: str = "ready"  # ready | partial | empty
    application: dict[str, Any] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    entry_points: dict[str, Any] = field(default_factory=dict)
    ui_signals: dict[str, Any] = field(default_factory=dict)
    libraries: list[dict[str, Any]] = field(default_factory=list)
    ads: dict[str, Any] = field(default_factory=dict)
    features: list[FeatureSignal] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    deep_links: list[DeepLinkSignal] = field(default_factory=list)
    activities: list[ActivityIntel] = field(default_factory=list)
    ad_trigger_hypotheses: list[AdTriggerHypothesis] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "application": dict(self.application),
            "components": dict(self.components),
            "permissions": dict(self.permissions),
            "entry_points": dict(self.entry_points),
            "ui_signals": dict(self.ui_signals),
            "libraries": list(self.libraries)[:40],
            "ads": dict(self.ads),
            "features": [f.to_dict() for f in self.features[:30]],
            "signals": dict(self.signals),
            "deep_links": [d.to_dict() for d in self.deep_links[:40]],
            "activities": [a.to_dict() for a in self.activities[:80]],
            "ad_trigger_hypotheses": [h.to_dict() for h in self.ad_trigger_hypotheses[:20]],
            "warnings": list(self.warnings)[:20],
        }

    def to_ai_summary(self) -> dict[str, Any]:
        """Compact summary for AIPlanningContext — never full APK dumps."""
        ads = self.ads or {}
        sdk_names = [
            s.get("name")
            for s in (ads.get("sdk_candidates") or [])
            if isinstance(s, dict) and s.get("name")
        ]
        formats = [
            {"format": f.get("format"), "confidence": f.get("confidence"), "kind": f.get("kind")}
            for f in (ads.get("ad_formats") or [])
            if isinstance(f, dict)
        ]
        return {
            "package": self.application.get("package_name"),
            "version_name": self.application.get("version_name"),
            "activities": self.components.get("activity_count", len(self.activities)),
            "services": self.components.get("service_count", 0),
            "launcher_activity": (self.entry_points.get("launcher_activities") or [None])[0],
            "exported_activities": len(self.entry_points.get("exported_activities") or []),
            "webview_present": bool(self.ui_signals.get("webview_present")),
            "deep_links": len(self.deep_links),
            "libraries": [
                lib.get("name")
                for lib in self.libraries[:12]
                if isinstance(lib, dict) and lib.get("name")
            ],
            "ad_sdk_signals": sdk_names[:8],
            "ad_format_signals": formats[:8],
            "features": [
                {"feature": f.feature, "confidence": f.confidence}
                for f in self.features[:12]
            ],
            "status": self.status,
            "note": "STATIC_EVIDENCE_ONLY — not runtime confirmation",
        }


def _clamp(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))
