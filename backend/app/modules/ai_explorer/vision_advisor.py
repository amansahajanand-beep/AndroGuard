"""Vision-guided tap choice: look at the screen the way a first-time user would.

The deterministic planner ranks taps from the UI tree, which cannot tell an ad card
from content when the ad has no accessibility hints. This advisor shows a screenshot
and the planner's own candidates to Claude and asks two things: which candidate a
person would tap next, and which candidates are ads or sponsored content.

Safety: the model can only pick from the numbered candidates it was given, it never
returns coordinates or commands, and every failure returns ``None`` so the caller
falls back to the deterministic choice.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are testing an Android app by using it exactly like a first-time human user. "
    "You get a screenshot and a numbered list of tappable candidates (label and pixel bounds). "
    "Decide what a person would tap next to move through the app: finish onboarding "
    "(language, permissions, Continue/Next), then explore real features, menus and tabs. "
    "Candidates that are advertisements, sponsored cards, 'Install'/'Download'/'Open' buttons of an ad, "
    "purchase or subscription prompts must never be chosen; list them under ad_candidates. "
    "Reply with JSON only, no prose: "
    '{"screen_kind": "<short description>", "choice": <candidate number or null>, '
    '"ad_candidates": [<numbers>], "reason": "<one short sentence>"}.'
)


@dataclass
class VisionChoice:
    choice_index: int | None = None
    ad_indexes: list[int] = field(default_factory=list)
    screen_kind: str = ""
    reason: str = ""


def downscale_png(png: bytes, max_width: int = 720) -> tuple[bytes, str]:
    """Shrink a screenshot to keep the request small; returns (bytes, media_type)."""
    from PIL import Image

    with Image.open(BytesIO(png)) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize((max_width, int(image.height * ratio)))
        out = BytesIO()
        image.save(out, format="JPEG", quality=70)
        return out.getvalue(), "image/jpeg"


def _describe(index: int, label: str, bounds: Sequence[int]) -> str:
    left, top, right, bottom = (list(bounds) + [0, 0, 0, 0])[:4]
    return f"{index}. \"{(label or '(no text)')[:60]}\" bounds=[{left},{top},{right},{bottom}]"


def parse_choice(text: str, candidate_count: int) -> VisionChoice | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None

    def valid(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = int(value)
        return number if 1 <= number <= candidate_count else None

    ads = []
    for item in data.get("ad_candidates") or []:
        number = valid(item)
        if number is not None and number not in ads:
            ads.append(number)
    choice = valid(data.get("choice"))
    if choice in ads:
        choice = None  # never act on something the model itself flagged as an ad
    return VisionChoice(
        choice_index=choice,
        ad_indexes=ads,
        screen_kind=str(data.get("screen_kind") or "")[:80],
        reason=str(data.get("reason") or "")[:200],
    )


def _anthropic_transport(body: dict[str, Any], *, api_key: str, api_base: str, timeout: float) -> str:
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return "".join(
        part.get("text", "") for part in payload.get("content", []) if isinstance(part, dict)
    )


def choose_with_vision(
    png: bytes,
    candidates: Sequence[tuple[str, Sequence[int]]],
    *,
    transport: Callable[..., str] | None = None,
) -> VisionChoice | None:
    """Ask the model what to tap. ``candidates`` are (label, bounds) in display order."""
    api_key = (settings.vision_planner_api_key or settings.anthropic_api_key or "").strip()
    if not api_key or not candidates:
        return None
    try:
        image_bytes, media_type = downscale_png(png)
        listing = "\n".join(_describe(i + 1, label, bounds) for i, (label, bounds) in enumerate(candidates))
        body = {
            "model": settings.vision_planner_model,
            "max_tokens": 300,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": "Candidates:\n" + listing},
                    ],
                }
            ],
        }
        send = transport or _anthropic_transport
        text = send(
            body,
            api_key=api_key,
            api_base=settings.vision_planner_api_base,
            timeout=float(settings.vision_planner_timeout_seconds),
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("[VISION-PLANNER] request failed: %s", type(exc).__name__)
        return None
    except Exception as exc:  # noqa: BLE001 - the advisor must never break exploration
        logger.info("[VISION-PLANNER] unexpected failure: %s", type(exc).__name__)
        return None
    return parse_choice(text, len(candidates))
