"""Anthropic Claude vision provider (optional — requires ANTHROPIC_API_KEY)."""

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


class ClaudeVisionProvider(AdVisionProvider):
    name = "claude"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "claude-sonnet-5-5",
        api_base: str = "https://api.anthropic.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        if not self.api_key:
            raise ProviderNotConfiguredError(
                "Claude vision provider requires ANTHROPIC_API_KEY "
                "(or AD_DETECTION_ANTHROPIC_API_KEY)."
            )
        path, width, height = load_image_meta(image_path)
        mime, b64 = encode_image_base64(path)
        media = "image/png" if "png" in mime else "image/jpeg" if "jpeg" in mime or "jpg" in mime else mime
        body = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0,
            "system": VISION_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Image size: {width}x{height}px. Detect advertisements and return JSON.",
                        },
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            f"{self.api_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Claude vision HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Claude vision request failed: {exc}") from exc

        blocks = payload.get("content") or []
        text = ""
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text += str(block.get("text") or "")
        return parse_vision_json(
            text or "{}",
            provider=self.name,
            image_path=str(path),
            image_width=width,
            image_height=height,
        )
