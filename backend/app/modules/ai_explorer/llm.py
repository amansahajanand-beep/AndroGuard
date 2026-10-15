"""Minimal OpenAI-compatible chat client for Phase 10 (no tool/shell execution).

Works with OpenAI and NVIDIA Integrate (`https://integrate.api.nvidia.com/v1`).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class AIAdvisorError(RuntimeError):
    pass


def chat_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint; return assistant text.

    Never logs API keys. Does not expose tools / function calling.
    """
    api_key = (settings.ai_explorer_api_key or settings.openai_api_key or "").strip()
    if not api_key:
        raise AIAdvisorError("AI explorer API key is not configured.")

    base = (
        settings.ai_explorer_api_base or "https://integrate.api.nvidia.com/v1"
    ).rstrip("/")
    model_name = (
        model or settings.ai_explorer_model or "nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    timeout = float(
        timeout_seconds
        if timeout_seconds is not None
        else settings.ai_explorer_timeout_seconds
    )

    payload: dict[str, Any] = {
        "model": model_name,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    # Optional; many NVIDIA models reject response_format.
    use_json_format = bool(settings.ai_explorer_json_response_format)
    if use_json_format:
        payload["response_format"] = {"type": "json_object"}

    try:
        return _post_chat(base=base, api_key=api_key, payload=payload, timeout=timeout)
    except AIAdvisorError:
        if not use_json_format or "response_format" not in payload:
            raise
        # Retry once without response_format for NVIDIA / other hosts.
        payload.pop("response_format", None)
        logger.info("Retrying AI chat without response_format")
        return _post_chat(base=base, api_key=api_key, payload=payload, timeout=timeout)


def _post_chat(
    *,
    base: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> str:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        logger.warning("AI advisor HTTP error status=%s detail=%s", exc.code, detail)
        raise AIAdvisorError(f"AI provider HTTP {exc.code}") from exc
    except Exception as exc:
        logger.warning("AI advisor request failed: %s", type(exc).__name__)
        raise AIAdvisorError(f"AI provider request failed: {type(exc).__name__}") from exc

    try:
        message = body["choices"][0]["message"]
        content = message.get("content")
        # Some providers return a list of content parts.
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
            content = "".join(parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise AIAdvisorError("AI provider returned an unexpected payload") from exc
    if not isinstance(content, str) or not content.strip():
        raise AIAdvisorError("AI provider returned empty content")
    return content
