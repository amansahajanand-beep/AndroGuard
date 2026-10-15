"""Shared vision-provider helpers (prompt + JSON parse). No emulator access."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.modules.ad_detection.models import (
    AdDetectionResult,
    BoundingBox,
    infer_position,
    normalize_ad_type,
)
from app.modules.ad_detection.providers.base import ensure_image_exists

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = """You analyze Android app screenshots for advertisement placements.
Return ONLY valid JSON (no markdown) with this shape:
{
  "ads": [
    {
      "detected": true,
      "type": "banner|native|interstitial|rewarded|unknown",
      "confidence": 0.0-1.0,
      "bounding_box": {"x": int, "y": int, "width": int, "height": int},
      "position": "top|bottom|middle|fullscreen|unknown"
    }
  ]
}
Rules:
- bounding_box uses pixel coordinates with origin at the top-left of the image.
- If no ad is visible, return {"ads": [{"detected": false, "type": "unknown", "confidence": 0.0, "bounding_box": null, "position": "unknown"}]}.
- Do not invent ads. Prefer fewer high-confidence detections.
- Never suggest UI actions or emulator commands.
"""


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def encode_image_base64(path: Path) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return mime, data


def parse_vision_json(
    text: str,
    *,
    provider: str,
    image_path: str,
    image_width: int,
    image_height: int,
) -> list[AdDetectionResult]:
    payload = _extract_json_object(text)
    ads = payload.get("ads")
    if ads is None and "detected" in payload:
        ads = [payload]
    if not isinstance(ads, list) or not ads:
        return [
            AdDetectionResult.none(
                provider=provider,
                image_path=image_path,
                image_width=image_width,
                image_height=image_height,
                evidence=["vision:empty_ads"],
            )
        ]

    results: list[AdDetectionResult] = []
    for item in ads:
        if not isinstance(item, dict):
            continue
        detected = bool(item.get("detected", False))
        box = BoundingBox.from_dict(item.get("bounding_box") if isinstance(item.get("bounding_box"), dict) else None)
        ad_type = normalize_ad_type(str(item.get("type") or "unknown"))
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        position = str(item.get("position") or "unknown").lower()
        if box and position in {"", "unknown"}:
            position = infer_position(box, image_width=image_width, image_height=image_height)
        if position not in {"top", "bottom", "middle", "fullscreen", "unknown"}:
            position = "unknown"
        results.append(
            AdDetectionResult(
                detected=detected and confidence > 0,
                type=ad_type,
                confidence=confidence,
                bounding_box=box if detected else None,
                position=position,  # type: ignore[arg-type]
                provider=provider,
                image_path=image_path,
                image_width=image_width,
                image_height=image_height,
                evidence=[f"vision:{provider}"],
                raw=dict(item),
            )
        )
    if not results:
        return [
            AdDetectionResult.none(
                provider=provider,
                image_path=image_path,
                image_width=image_width,
                image_height=image_height,
                evidence=["vision:parse_miss"],
            )
        ]
    return results


def load_image_meta(image_path: str | Path) -> tuple[Path, int, int]:
    path = ensure_image_exists(image_path)
    try:
        width, height = image_dimensions(path)
    except UnidentifiedImageError as exc:
        raise ValueError(f"Not a readable image: {path}") from exc
    return path, width, height


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        logger.warning("Vision provider returned non-JSON text")
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
