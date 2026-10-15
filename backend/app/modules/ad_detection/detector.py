"""AdDetector facade — screenshot in, AdDetectionResult out. No emulator control."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from app.modules.ad_detection.models import AdDetectionResult
from app.modules.ad_detection.providers.base import AdVisionProvider, pick_best

logger = logging.getLogger(__name__)


class AdDetector:
    """Analyzes unique screenshots for visible advertisements.

    Architecture::

        Screenshot
            ↓
        AdDetector.detect(image_path)
            ↓
        AdVisionProvider.analyze(...)
            ↓
        AdDetectionResult

    The selected provider is injectable so OpenAI / Gemini / Claude / local /
    object-detection backends can be swapped without touching exploration code.
    """

    def __init__(self, provider: AdVisionProvider, *, min_confidence: float = 0.0) -> None:
        self.provider = provider
        self.min_confidence = min_confidence

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", type(self.provider).__name__)

    def detect(self, image_path: str | Path) -> AdDetectionResult:
        """Detect the primary advertisement on ``image_path``."""
        path = Path(image_path)
        logger.info("[AD_DETECT] provider=%s image=%s", self.provider_name, path)
        results = self.detect_all(path)
        primary = pick_best(results, provider=self.provider_name, image_path=str(path))
        if primary.detected and primary.confidence < self.min_confidence:
            logger.info(
                "[AD_DETECT] below min_confidence=%.2f (got %.2f) — treating as none",
                self.min_confidence,
                primary.confidence,
            )
            return AdDetectionResult.none(
                provider=self.provider_name,
                image_path=str(path),
                image_width=primary.image_width,
                image_height=primary.image_height,
                evidence=[
                    *primary.evidence,
                    f"filtered:min_confidence={self.min_confidence}",
                ],
            )
        logger.info(
            "[AD_DETECT] detected=%s type=%s conf=%.3f pos=%s",
            primary.detected,
            primary.type,
            primary.confidence,
            primary.position,
        )
        return primary

    def detect_all(self, image_path: str | Path) -> list[AdDetectionResult]:
        """Return every detection the provider reports for the screenshot."""
        results = self.provider.analyze(image_path)
        if self.min_confidence <= 0:
            return list(results)
        filtered = [
            item
            for item in results
            if (not item.detected) or item.confidence >= self.min_confidence
        ]
        return filtered or list(results)

    def detect_many(self, image_paths: Sequence[str | Path]) -> list[AdDetectionResult]:
        """Run ``detect`` on each path (one primary result per screenshot)."""
        return [self.detect(path) for path in image_paths]
