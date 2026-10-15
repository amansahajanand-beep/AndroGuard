"""Phase 6: screenshot advertisement detection (vision providers, no emulator control).

Architecture::

    Screenshot → AdDetector.detect(image_path) → AdDetectionResult

Providers are swappable: heuristic (default), OpenAI, Gemini, Claude, local, OD.
"""

from app.modules.ad_detection.detector import AdDetector
from app.modules.ad_detection.factory import build_ad_detector, build_provider
from app.modules.ad_detection.models import (
    AdDetectionResult,
    BoundingBox,
    infer_position,
    normalize_ad_type,
)
from app.modules.ad_detection.providers import (
    AdVisionProvider,
    ClaudeVisionProvider,
    GeminiVisionProvider,
    HeuristicAdProvider,
    LocalVisionProvider,
    ObjectDetectionProvider,
    OpenAIVisionProvider,
    ProviderNotConfiguredError,
)

__all__ = [
    "AdDetectionResult",
    "AdDetector",
    "AdVisionProvider",
    "BoundingBox",
    "ClaudeVisionProvider",
    "GeminiVisionProvider",
    "HeuristicAdProvider",
    "LocalVisionProvider",
    "ObjectDetectionProvider",
    "OpenAIVisionProvider",
    "ProviderNotConfiguredError",
    "build_ad_detector",
    "build_provider",
    "infer_position",
    "normalize_ad_type",
]
