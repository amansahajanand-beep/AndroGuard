"""Placeholder providers for local / object-detection backends.

Wire a real ONNX/YOLO or on-device VLM later; the AdDetector API stays stable.
"""

from __future__ import annotations

from pathlib import Path

from app.modules.ad_detection.models import AdDetectionResult
from app.modules.ad_detection.providers.base import AdVisionProvider, ProviderNotConfiguredError
from app.modules.ad_detection.providers.heuristic import HeuristicAdProvider
from app.modules.ad_detection.providers.vision_common import load_image_meta


class LocalVisionProvider(AdVisionProvider):
    """Reserved for a future local VLM. Falls back to heuristic when enabled loosely."""

    name = "local"

    def __init__(self, *, model_path: str | None = None, allow_heuristic_fallback: bool = True) -> None:
        self.model_path = (model_path or "").strip()
        self.allow_heuristic_fallback = allow_heuristic_fallback
        self._heuristic = HeuristicAdProvider()

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        if not self.model_path:
            if self.allow_heuristic_fallback:
                results = self._heuristic.analyze(image_path)
                for item in results:
                    item.provider = self.name
                    item.evidence = [*item.evidence, "local:heuristic_fallback"]
                return results
            raise ProviderNotConfiguredError(
                "Local vision provider requires AD_DETECTION_LOCAL_MODEL_PATH."
            )
        # Future: load ONNX/VLM weights from model_path.
        raise ProviderNotConfiguredError(
            f"Local vision model loading is not implemented yet (path={self.model_path}). "
            "Use provider=heuristic|openai|gemini|claude for now."
        )


class ObjectDetectionProvider(AdVisionProvider):
    """Reserved for a future object-detection model (YOLO / custom ad boxes)."""

    name = "object_detection"

    def __init__(self, *, model_path: str | None = None) -> None:
        self.model_path = (model_path or "").strip()

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        path, width, height = load_image_meta(image_path)
        if not self.model_path:
            raise ProviderNotConfiguredError(
                "Object-detection provider requires AD_DETECTION_OD_MODEL_PATH."
            )
        raise ProviderNotConfiguredError(
            f"Object-detection inference is not implemented yet (path={self.model_path}). "
            f"Image OK: {path.name} ({width}x{height})."
        )
