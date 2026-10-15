"""Pick the model provider for the AI report and the privacy-policy check.

``AI_REPORT_PROVIDER`` is ``anthropic`` (default) or ``nvidia`` / ``openai``. The last two use an
OpenAI-compatible ``/chat/completions`` endpoint, so an NVIDIA ``nvapi-`` key works. The callers
build one Anthropic-shaped request body; this module converts it when the provider needs another
shape, so the report code does not care which provider answers.

Text only. Screenshots (the vision planner) still use Anthropic.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.core.config import settings

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
OPENAI_BASE = "https://api.openai.com/v1"


def provider() -> str:
    value = (settings.ai_report_provider or "anthropic").strip().lower()
    return value if value in {"anthropic", "nvidia", "openai"} else "anthropic"


def api_key() -> str:
    key = (settings.ai_report_api_key or "").strip()
    if key:
        return key
    if provider() == "anthropic":
        return (settings.anthropic_api_key or "").strip()
    if provider() == "nvidia":
        return (settings.ai_explorer_api_key or settings.openai_api_key or "").strip()
    return (settings.openai_api_key or "").strip()


def api_base() -> str:
    configured = (settings.ai_report_api_base or "").strip()
    kind = provider()
    if kind == "anthropic":
        return configured or "https://api.anthropic.com"
    default = NVIDIA_BASE if kind == "nvidia" else OPENAI_BASE
    # The setting defaults to Anthropic's host; ignore that default for other providers.
    if not configured or "anthropic.com" in configured:
        return settings.ai_explorer_api_base if kind == "nvidia" and settings.ai_explorer_api_base else default
    return configured


def model() -> str:
    configured = (settings.ai_report_model or "").strip()
    if provider() != "anthropic" and (not configured or configured.lower().startswith("claude")):
        return (settings.ai_explorer_model or "").strip() or "nvidia/nemotron-3.5-lightning-30b-a3b"
    return configured


def configured() -> bool:
    return bool(settings.ai_report_enabled and api_key())


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _openai_transport(body: dict[str, Any], *, api_key: str, api_base: str, timeout: float) -> str:
    """Retry with a short back-off: hosted endpoints occasionally rate-limit or time out a single request."""
    last: Exception | None = None
    for delay in (0.0, 3.0, 6.0):
        if delay:
            time.sleep(delay)
        try:
            return _openai_once(body, api_key=api_key, api_base=api_base, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last = exc
    assert last is not None
    raise last


def _openai_once(body: dict[str, Any], *, api_key: str, api_base: str, timeout: float) -> str:
    from app.modules.ai_explorer.llm import _post_chat

    messages: list[dict[str, str]] = []
    if body.get("system"):
        messages.append({"role": "system", "content": str(body["system"])})
    for message in body.get("messages", []):
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        messages.append({"role": message.get("role", "user"), "content": str(content)})
    payload = {
        "model": body["model"],
        "temperature": body.get("temperature", 0),
        "max_tokens": body.get("max_tokens", 1200),
        "messages": messages,
    }
    base = api_base.rstrip("/")
    if provider() == "nvidia" and settings.ai_report_disable_thinking:
        # Reasoning models (Nemotron) otherwise spend the whole token budget thinking and return no answer.
        try:
            text = _post_chat(
                base=base,
                api_key=api_key,
                payload={**payload, "chat_template_kwargs": {"enable_thinking": False}},
                timeout=timeout,
            )
            return _THINK.sub("", text).strip()
        except Exception:  # noqa: BLE001 - this model may not accept the setting; retry with room to think
            payload = {**payload, "max_tokens": int(payload["max_tokens"]) * 5}
    text = _post_chat(base=base, api_key=api_key, payload=payload, timeout=timeout)
    # Some reasoning models print their thinking first; it can contain braces that confuse JSON parsing.
    return _THINK.sub("", text).strip()


def transport():
    """The function that sends a request body and returns the reply text."""
    if provider() == "anthropic":
        from app.modules.ai_explorer.vision_advisor import _anthropic_transport

        return _anthropic_transport
    return _openai_transport
