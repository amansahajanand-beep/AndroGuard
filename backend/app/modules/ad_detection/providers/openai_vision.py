"""OpenAI vision provider (optional — requires OPENAI_API_KEY)."""

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


class OpenAIVisionProvider(AdVisionProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gpt-4o-mini",
        api_base: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_path: str | Path) -> list[AdDetectionResult]:
        if not self.api_key:
            raise ProviderNotConfiguredError(
                "OpenAI vision provider requires OPENAI_API_KEY (or AD_DETECTION_OPENAI_API_KEY)."
            )
        path, width, height = load_image_meta(image_path)
        mime, b64 = encode_image_base64(path)
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Image size: {width}x{height}px. "
                                "Detect advertisements and return JSON."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"OpenAI vision HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI vision request failed: {exc}") from exc

        text = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return parse_vision_json(
            text or "{}",
            provider=self.name,
            image_path=str(path),
            image_width=width,
            image_height=height,
        )
