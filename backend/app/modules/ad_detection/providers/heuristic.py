"""Offline heuristic ad detector (no cloud / no LLM).

Uses image geometry + simple band energy to guess banner / interstitial
placements. Intentionally conservative — vision providers should override when
configured.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError

from app.modules.ad_detection.models import (
    AdDetectionResult,
    BoundingBox,
    infer_position,
    normalize_ad_type,
)
from app.modules.ad_detection.providers.base import AdVisionProvider, ensure_image_exists

logger = logging.getLogger(__name__)


class HeuristicAdProvider(AdVisionProvider):
    """Deterministic screenshot heuristics — never talks to an API."""

    name = "heuristic"

    def __init__(self, *, min_confidence: float = 0.45) -> None:
        self.min_confidence = min_confidence

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        path = ensure_image_exists(image_path)
        try:
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                width, height = rgb.size
                bands = self._scan_bands(rgb)
        except UnidentifiedImageError as exc:
            raise ValueError(f"Not a readable image: {path}") from exc

        results: list[AdDetectionResult] = []
        for candidate in bands:
            box, ad_type, confidence, evidence = candidate
            if confidence < self.min_confidence:
                continue
            results.append(
                AdDetectionResult(
                    detected=True,
                    type=normalize_ad_type(ad_type),
                    confidence=confidence,
                    bounding_box=box,
                    position=infer_position(box, image_width=width, image_height=height),
                    provider=self.name,
                    image_path=str(path),
                    image_width=width,
                    image_height=height,
                    evidence=evidence,
                )
            )
        if not results:
            return [
                AdDetectionResult.none(
                    provider=self.name,
                    image_path=str(path),
                    image_width=width,
                    image_height=height,
                    evidence=["heuristic:no_ad_band"],
                )
            ]
        return results

    def _scan_bands(
        self, image: Image.Image
    ) -> list[tuple[BoundingBox, str, float, list[str]]]:
        width, height = image.size
        if width < 32 or height < 32:
            return []

        found: list[tuple[BoundingBox, str, float, list[str]]] = []

        # Top / bottom banner strips.
        for label, y0, y1 in (
            ("top", 0, max(1, int(height * 0.14))),
            ("bottom", int(height * 0.82), height),
        ):
            band = image.crop((0, y0, width, y1))
            score = self._band_score(band)
            band_h = y1 - y0
            if score >= 0.55 and band_h / height <= 0.22:
                box = BoundingBox(x=0, y=y0, width=width, height=band_h)
                confidence = min(0.85, 0.45 + score * 0.4)
                found.append(
                    (
                        box,
                        "banner",
                        confidence,
                        [f"heuristic:band_{label}", f"heuristic:score={score:.2f}"],
                    )
                )

        # Near-fullscreen interstitial: high coverage mid-frame contrast.
        mid = image.crop((int(width * 0.05), int(height * 0.08), int(width * 0.95), int(height * 0.92)))
        mid_score = self._band_score(mid)
        if mid_score >= 0.72:
            box = BoundingBox(
                x=int(width * 0.05),
                y=int(height * 0.08),
                width=int(width * 0.90),
                height=int(height * 0.84),
            )
            found.append(
                (
                    box,
                    "interstitial",
                    min(0.80, 0.50 + mid_score * 0.3),
                    [f"heuristic:fullscreen_score={mid_score:.2f}"],
                )
            )

        # Middle native-ish band.
        native = image.crop((int(width * 0.05), int(height * 0.30), int(width * 0.95), int(height * 0.62)))
        native_score = self._band_score(native)
        if native_score >= 0.62 and not any(item[1] == "interstitial" for item in found):
            box = BoundingBox(
                x=int(width * 0.05),
                y=int(height * 0.30),
                width=int(width * 0.90),
                height=int(height * 0.32),
            )
            found.append(
                (
                    box,
                    "native",
                    min(0.75, 0.40 + native_score * 0.35),
                    [f"heuristic:native_score={native_score:.2f}"],
                )
            )

        return found

    def _band_score(self, band: Image.Image) -> float:
        """Rough saliency: higher when the region is colorful / contrasty."""
        stat = ImageStat.Stat(band)
        # Mean channel spread + std-dev energy, normalized loosely to 0..1.
        means = stat.mean or [0, 0, 0]
        stdevs = stat.stddev or [0, 0, 0]
        colorfulness = abs(means[0] - means[1]) + abs(means[1] - means[2]) + abs(means[0] - means[2])
        energy = sum(stdevs) / 3.0
        score = (colorfulness / 120.0) * 0.45 + (energy / 80.0) * 0.55
        return max(0.0, min(1.0, score))
