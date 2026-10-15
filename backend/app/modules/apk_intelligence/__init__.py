"""Phase 12F — APK Intelligence (static evidence → agent context).

Builds ApplicationIntelligence from existing static analysis output.
Does not re-parse APKs or execute code.
"""

from app.modules.apk_intelligence.builder import build_application_intelligence
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

__all__ = [
    "ActivityIntel",
    "AdFormatSignal",
    "AdSdkSignal",
    "AdTriggerHypothesis",
    "AdTriggerSignal",
    "ApplicationIntelligence",
    "DeepLinkSignal",
    "FeatureSignal",
    "StaticEvidence",
    "build_application_intelligence",
]
