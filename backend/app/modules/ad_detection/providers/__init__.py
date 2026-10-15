"""Provider registry exports."""

from app.modules.ad_detection.providers.base import (
    AdVisionProvider,
    ProviderNotConfiguredError,
    ensure_image_exists,
    pick_best,
)
from app.modules.ad_detection.providers.claude_vision import ClaudeVisionProvider
from app.modules.ad_detection.providers.gemini_vision import GeminiVisionProvider
from app.modules.ad_detection.providers.heuristic import HeuristicAdProvider
from app.modules.ad_detection.providers.local_vision import (
    LocalVisionProvider,
    ObjectDetectionProvider,
)
from app.modules.ad_detection.providers.openai_vision import OpenAIVisionProvider

__all__ = [
    "AdVisionProvider",
    "ClaudeVisionProvider",
    "GeminiVisionProvider",
    "HeuristicAdProvider",
    "LocalVisionProvider",
    "ObjectDetectionProvider",
    "OpenAIVisionProvider",
    "ProviderNotConfiguredError",
    "ensure_image_exists",
    "pick_best",
]
