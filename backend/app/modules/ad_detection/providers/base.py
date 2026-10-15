"""Provider interface for screenshot advertisement vision backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from app.modules.ad_detection.models import AdDetectionResult


class AdVisionProvider(ABC):
    """Analyzes a screenshot. Never issues emulator / adb commands."""

    name: str = "base"

    @abstractmethod
    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        """Return zero or more ad detections for ``image_path``."""

    def analyze_primary(self, image_path: str | Path) -> AdDetectionResult:
        results = self.analyze(image_path)
        if not results:
            return AdDetectionResult.none(provider=self.name, image_path=str(image_path))
        # Highest confidence first; prefer detected=True.
        ranked = sorted(
            results,
            key=lambda item: (item.detected, item.confidence),
            reverse=True,
        )
        return ranked[0]


class ProviderNotConfiguredError(RuntimeError):
    """Raised when a vision provider is selected but credentials/models are missing."""


def ensure_image_exists(image_path: str | Path) -> Path:
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Screenshot not found: {path}")
    return path


def pick_best(results: Sequence[AdDetectionResult], *, provider: str, image_path: str) -> AdDetectionResult:
    if not results:
        return AdDetectionResult.none(provider=provider, image_path=image_path)
    return max(results, key=lambda item: (item.detected, item.confidence))
