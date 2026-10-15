"""Google Gemini vision provider (optional — requires GEMINI_API_KEY)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from app.modules.ad_detection.models import AdDetectionResult
from app.modules.ad_detection.providers.base import AdVisionProvider, ProviderNotConfiguredError
from app.modules.ad_detection.providers.vision_common import (
    VISION_SYSTEM_PROMPT,
    encode_image_base64,
    load_image_meta,
    parse_vision_json,
)

logger = logging.getLogger(__name__)


class GeminiVisionProvider(AdVisionProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gemini-1.5-flash",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        if not self.api_key:
            raise ProviderNotConfiguredError(
                "Gemini vision provider requires GEMINI_API_KEY (or AD_DETECTION_GEMINI_API_KEY)."
            )
        path, width, height = load_image_meta(image_path)
        mime, b64 = encode_image_base64(path)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"{VISION_SYSTEM_PROMPT}\n"
                                f"Image size: {width}x{height}px."
                            )
                        },
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Gemini vision HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini vision request failed: {exc}") from exc

        candidates = payload.get("candidates") or []
        parts = (
            candidates[0].get("content", {}).get("parts", []) if candidates else []
        )
        text = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text += str(part["text"])
        return parse_vision_json(
            text or "{}",
            provider=self.name,
            image_path=str(path),
            image_width=width,
            image_height=height,
        )
