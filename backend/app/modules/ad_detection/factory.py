"""Build an :class:`AdDetector` from settings / explicit provider name."""

from __future__ import annotations

from app.core.config import settings
from app.modules.ad_detection.detector import AdDetector
from app.modules.ad_detection.providers import (
    AdVisionProvider,
    ClaudeVisionProvider,
    GeminiVisionProvider,
    HeuristicAdProvider,
    LocalVisionProvider,
    ObjectDetectionProvider,
    OpenAIVisionProvider,
)


def build_provider(name: str | None = None) -> AdVisionProvider:
    """Instantiate the configured vision backend (no emulator coupling)."""
    provider_name = (name or settings.ad_detection_provider or "heuristic").strip().lower()
    timeout = settings.ad_detection_timeout_seconds

    if provider_name in {"heuristic", "offline", "default"}:
        return HeuristicAdProvider(min_confidence=settings.ad_detection_min_confidence)

    if provider_name in {"openai", "gpt"}:
        return OpenAIVisionProvider(
            api_key=settings.ad_detection_openai_api_key or settings.openai_api_key,
            model=settings.ad_detection_openai_model,
            api_base=settings.ad_detection_openai_api_base,
            timeout_seconds=timeout,
        )

    if provider_name in {"gemini", "google"}:
        return GeminiVisionProvider(
            api_key=settings.ad_detection_gemini_api_key or settings.gemini_api_key,
            model=settings.ad_detection_gemini_model,
            timeout_seconds=timeout,
        )

    if provider_name in {"claude", "anthropic"}:
        return ClaudeVisionProvider(
            api_key=settings.ad_detection_anthropic_api_key or settings.anthropic_api_key,
            model=settings.ad_detection_claude_model,
            api_base=settings.ad_detection_anthropic_api_base,
            timeout_seconds=timeout,
        )

    if provider_name in {"local", "local_vision"}:
        return LocalVisionProvider(
            model_path=settings.ad_detection_local_model_path,
            allow_heuristic_fallback=settings.ad_detection_local_fallback_heuristic,
        )

    if provider_name in {"object_detection", "od", "yolo"}:
        return ObjectDetectionProvider(model_path=settings.ad_detection_od_model_path)

    raise ValueError(
        f"Unknown ad detection provider '{provider_name}'. "
        "Use heuristic|openai|gemini|claude|local|object_detection."
    )


def build_ad_detector(provider_name: str | None = None) -> AdDetector:
    """Factory used by CLI / future pipeline stages."""
    if not settings.ad_detection_enabled and provider_name is None:
        # Still allow explicit CLI override; default path respects the flag by
        # falling back to heuristic so offline analysis always works.
        provider = HeuristicAdProvider(min_confidence=settings.ad_detection_min_confidence)
    else:
        provider = build_provider(provider_name)
    return AdDetector(provider, min_confidence=settings.ad_detection_min_confidence)
