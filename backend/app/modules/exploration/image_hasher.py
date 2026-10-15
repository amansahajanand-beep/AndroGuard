"""Perceptual image hashing for near-duplicate screenshot detection.

Uses Pillow only (no extra deps). Combines average-hash and difference-hash so
small animation / clock-pixel noise does not invent a new visual state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.modules.exploration.errors import ScreenshotDecodeError


@dataclass(frozen=True)
class ImageHashResult:
    """Combined perceptual hash for one image."""

    algorithm: str
    ahash: str
    dhash: str
    combined: str
    hash_size: int
    width: int
    height: int

    @property
    def hex(self) -> str:
        return self.combined


class ImageHasher:
    """Configurable perceptual hasher with Hamming-distance similarity."""

    def __init__(
        self,
        *,
        hash_size: int | None = None,
        crop_top: float | None = None,
        crop_bottom: float | None = None,
    ) -> None:
        self.hash_size = max(4, int(hash_size or settings.exploration_hash_size))
        self.crop_top = _clamp01(crop_top if crop_top is not None else settings.exploration_hash_crop_top)
        self.crop_bottom = _clamp01(
            crop_bottom if crop_bottom is not None else settings.exploration_hash_crop_bottom
        )

    def hash_bytes(self, data: bytes) -> ImageHashResult:
        image = self._open(data)
        return self.hash_image(image)

    def hash_path(self, path: str) -> ImageHashResult:
        try:
            with Image.open(path) as image:
                return self.hash_image(image.copy())
        except (OSError, UnidentifiedImageError) as exc:
            raise ScreenshotDecodeError(f"Could not open image at {path}: {exc}") from exc

    def hash_image(self, image: Image.Image) -> ImageHashResult:
        prepared = self._prepare(image)
        width, height = prepared.size
        ahash = self._average_hash(prepared)
        dhash = self._difference_hash(prepared)
        combined = hashlib.sha256(f"{ahash}:{dhash}".encode("ascii")).hexdigest()[:32]
        return ImageHashResult(
            algorithm="ahash+dhash",
            ahash=ahash,
            dhash=dhash,
            combined=combined,
            hash_size=self.hash_size,
            width=width,
            height=height,
        )

    def hamming(self, left: str, right: str) -> int:
        """Bit distance between two equal-length hex hashes."""
        if len(left) != len(right):
            raise ValueError("Hash lengths must match for Hamming distance.")
        a = int(left, 16)
        b = int(right, 16)
        return (a ^ b).bit_count()

    def similarity(self, left: ImageHashResult, right: ImageHashResult) -> float:
        """Similarity in ``[0, 1]`` using the worse (more different) of aHash/dHash.

        Taking the min of the two keeps us from calling animated frames "identical"
        when only one hash channel stays stable.
        """
        bits = self.hash_size * self.hash_size
        a_sim = 1.0 - (self.hamming(left.ahash, right.ahash) / bits)
        d_sim = 1.0 - (self.hamming(left.dhash, right.dhash) / bits)
        return max(0.0, min(1.0, min(a_sim, d_sim)))

    def is_similar(
        self,
        left: ImageHashResult,
        right: ImageHashResult,
        *,
        threshold: float | None = None,
    ) -> bool:
        limit = threshold if threshold is not None else settings.exploration_state_similarity_threshold
        return self.similarity(left, right) >= limit

    # -- internals -----------------------------------------------------------

    def _open(self, data: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(data)) as image:
                return image.copy()
        except (OSError, UnidentifiedImageError) as exc:
            raise ScreenshotDecodeError(f"Could not decode screenshot PNG: {exc}") from exc

    def _prepare(self, image: Image.Image) -> Image.Image:
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        width, height = rgb.size
        top = int(height * self.crop_top)
        bottom = int(height * (1.0 - self.crop_bottom))
        if bottom <= top + 8:
            top, bottom = 0, height
        cropped = rgb.crop((0, top, width, bottom))
        # Mild blur via downscale reduces spinner / anti-alias flicker.
        return cropped

    def _average_hash(self, image: Image.Image) -> str:
        size = self.hash_size
        gray = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        pixels = list(gray.get_flattened_data()) if hasattr(gray, "get_flattened_data") else list(gray.getdata())
        avg = sum(pixels) / len(pixels)
        bits = 0
        for index, value in enumerate(pixels):
            if value >= avg:
                bits |= 1 << index
        return f"{bits:0{size * size // 4}x}"

    def _difference_hash(self, image: Image.Image) -> str:
        size = self.hash_size
        # dHash compares adjacent horizontal pixels; width is size+1.
        gray = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        bits = 0
        index = 0
        for y in range(size):
            for x in range(size):
                left = gray.getpixel((x, y))
                right = gray.getpixel((x + 1, y))
                if left < right:
                    bits |= 1 << index
                index += 1
        return f"{bits:0{size * size // 4}x}"


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clamp01(value: float) -> float:
    return max(0.0, min(0.45, float(value)))
