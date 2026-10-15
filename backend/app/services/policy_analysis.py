"""Compare what a privacy policy says with what the app actually does.

The model reads the policy and the numbered fact sheet and returns what the policy claims
plus any mismatches. Nothing it says is trusted until it is checked:

* every claim must carry a quote that appears word for word in the policy text,
* every mismatch about app behaviour must cite fact ids that exist in the fact sheet,
* a "contradiction" must refer to a topic the policy really does make a claim about.

Anything that fails a check is dropped and counted, never shown.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from app.core.config import settings
from app.services import ai_provider
from app.services.audit_evidence import Fact, fact_ids, render_facts

logger = logging.getLogger(__name__)

TOPICS = (
    "location", "contacts", "camera", "microphone", "storage", "device_ids", "ads", "analytics",
    "third_party_sharing", "children", "retention", "deletion", "security", "other",
)
ISSUE_TYPES = ("undisclosed_data_use", "contradiction", "vague_or_missing")
SEVERITIES = ("high", "medium", "low")

SYSTEM_PROMPT = (
    "You compare an app's privacy policy with facts extracted from the app itself, for Google Play "
    "Data Safety and User Data policy compliance. Use ONLY the policy text and the numbered facts. "
    "Do not assume anything the facts do not state. "
    "First list what the policy claims (each claim needs a short quote copied EXACTLY from the policy). "
    "Then list mismatches. Rules, all of them strict: "
    "(1) undisclosed_data_use: a fact shows the app can access or share a USER DATA category (a sensitive "
    "permission such as contacts, location, camera, microphone, storage, SMS, phone state; an advertising or "
    "analytics SDK) AND the policy says nothing at all about that category. If the policy mentions the category "
    "anywhere, even briefly, do NOT report it. "
    "(2) Generic facts are not data categories: network calls, target SDK, exported components, dynamic code "
    "loading and similar must never be cited as undisclosed data use. "
    "(3) ACCESS_COARSE_LOCATION means approximate location and ACCESS_FINE_LOCATION means precise location; do "
    "not report approximate-versus-precise wording as a mismatch when the policy mentions location. "
    "(4) contradiction: the policy explicitly states the opposite of a fact (quote it), for example it says the "
    "app has no ads but an advertising SDK is present. "
    "(5) vague_or_missing: only for a required section that is entirely absent (data deletion, retention, contact "
    "details), at most 2, never above medium severity. Do not nitpick wording. "
    "(6) severity high only for sensitive data (contacts, SMS, call log, precise location, camera, microphone) or "
    "a flat contradiction. "
    "Every mismatch about app behaviour must cite fact ids. If the policy and facts agree, return an empty issues "
    "list; an empty list is a good answer. "
    "Reply with JSON only: "
    '{"summary": "<=80 words", '
    '"claims": [{"topic": "location|contacts|camera|microphone|storage|device_ids|ads|analytics|third_party_sharing|children|retention|deletion|security|other", '
    '"statement": "", "quote": ""}], '
    '"issues": [{"type": "undisclosed_data_use|contradiction|vague_or_missing", "severity": "high|medium|low", '
    '"title": "", "explanation": "", "evidence_ids": ["fact id"], "claim_topics": ["topic"], "recommended_fix": ""}]}. '
    "At most 12 claims and 8 issues."
)


def _norm(text: str) -> str:
    text = re.sub(r"[‘’“”]", "'", text)
    return re.sub(r"\s+", " ", text).strip().lower()


# Facts about the app's code or setup, not about a category of user data. They can never back "undisclosed data use".
_NON_DATA_PREFIXES = ("code:", "components:", "app:", "policy:", "explore:")

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "location": ("location", "gps"),
    "contacts": ("contact", "address book"),
    "camera": ("camera", "photo"),
    "microphone": ("microphone", "audio", "voice"),
    "storage": ("storage", "files", "media"),
    "device_ids": ("device id", "identifier", "advertising id", "imei", "phone state"),
    "ads": ("advertis", "admob", " ads", "ad network"),
    "analytics": ("analytic", "usage data", "crash"),
    "sms": ("sms", "text message"),
    "call_log": ("call log", "call history"),
}
_PERMISSION_TOPICS = (
    ("LOCATION", "location"), ("CONTACTS", "contacts"), ("GET_ACCOUNTS", "contacts"), ("CAMERA", "camera"),
    ("RECORD_AUDIO", "microphone"), ("STORAGE", "storage"), ("READ_MEDIA", "storage"),
    ("READ_PHONE_STATE", "device_ids"), ("SMS", "sms"), ("CALL_LOG", "call_log"),
)
_ANALYTICS_SDK_HINTS = ("analytics", "firebase", "crashlytics", "amplitude", "mixpanel", "flurry", "appsflyer", "adjust")


def fact_topics(fact_id: str) -> set[str]:
    """The user-data topics a fact is about (used to check the policy actually covers them)."""
    kind, _, name = fact_id.partition(":")
    if kind == "perm":
        return {topic for needle, topic in _PERMISSION_TOPICS if needle in name.upper()}
    if kind == "sdk":
        topics = {"ads"} if any(h in name for h in ("admob", "ads", "applovin", "unity", "ironsource", "mintegral", "vungle", "chartboost", "audience", "inmobi", "pangle", "adcolony")) else set()
        if any(h in name for h in _ANALYTICS_SDK_HINTS):
            topics.add("analytics")
        return topics
    if kind == "ad":
        return {"ads"}
    return set()


def _policy_covers(haystack: str, topics: set[str]) -> bool:
    return bool(topics) and all(any(k in haystack for k in TOPIC_KEYWORDS.get(t, ())) for t in topics)


def validate(raw: dict[str, Any], policy_text: str, known_fact_ids: set[str]) -> dict[str, Any]:
    haystack = _norm(policy_text)
    dropped = 0

    claims: list[dict[str, str]] = []
    for item in (raw.get("claims") or [])[:12]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        quote = str(item.get("quote") or "").strip().strip("\"'")
        norm_quote = _norm(quote)
        if not (15 <= len(norm_quote) <= 400) or norm_quote not in haystack:
            dropped += 1
            continue
        topic = str(item.get("topic") or "other").lower()
        claims.append(
            {
                "id": f"c{len(claims) + 1}",
                "topic": topic if topic in TOPICS else "other",
                "statement": str(item.get("statement") or "").strip()[:300],
                "quote": quote[:400],
            }
        )
    claim_topics = {c["topic"] for c in claims}

    issues: list[dict[str, Any]] = []
    for item in (raw.get("issues") or [])[:8]:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            dropped += 1
            continue
        kind = str(item.get("type") or "").lower()
        if kind not in ISSUE_TYPES:
            dropped += 1
            continue
        evidence = [e for e in (item.get("evidence_ids") or []) if isinstance(e, str) and e in known_fact_ids]
        topics = [t for t in (item.get("claim_topics") or []) if isinstance(t, str) and t in TOPICS]
        if kind == "undisclosed_data_use":
            # Only facts about user data can back this; generic code facts cannot.
            evidence = [e for e in evidence if not e.startswith(_NON_DATA_PREFIXES)]
        if kind in {"undisclosed_data_use", "contradiction"} and not evidence:
            dropped += 1
            continue
        if kind == "undisclosed_data_use":
            covered_topics: set[str] = set().union(*(fact_topics(e) for e in evidence))
            if _policy_covers(haystack, covered_topics):
                # The policy does mention these categories, so "not disclosed" is wrong.
                dropped += 1
                continue
        if kind == "contradiction" and not (set(topics) & claim_topics):
            dropped += 1
            continue
        severity = str(item.get("severity") or "medium").lower()
        if kind == "vague_or_missing" and severity == "high":
            severity = "medium"
        if kind == "vague_or_missing" and sum(1 for i in issues if i["type"] == "vague_or_missing") >= 2:
            dropped += 1
            continue
        issues.append(
            {
                "type": kind,
                "severity": severity if severity in SEVERITIES else "medium",
                "title": str(item["title"]).strip()[:140],
                "explanation": str(item.get("explanation") or "").strip()[:600],
                "evidence_ids": evidence,
                "claim_ids": [c["id"] for c in claims if c["topic"] in topics],
                "recommended_fix": str(item.get("recommended_fix") or "").strip()[:400],
            }
        )
    return {
        "summary": str(raw.get("summary") or "").strip()[:600],
        "claims": claims,
        "issues": issues,
        "unsupported_dropped": dropped,
    }


def parse_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def analyze_policy(
    policy_text: str,
    facts: list[Fact],
    *,
    source: str,
    transport: Callable[..., str] | None = None,
) -> dict[str, Any] | None:
    if not ai_provider.configured():
        return None
    limit = int(settings.ai_policy_max_chars)
    truncated = len(policy_text) > limit
    clipped = policy_text[:limit]
    raw = None
    try:
        body = {
            "model": ai_provider.model(),
            "max_tokens": 3500,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"App facts:\n{render_facts(facts)}\n\nPrivacy policy text:\n<<<\n{clipped}\n>>>",
                }
            ],
        }
        for _attempt in range(2):
            reply = (transport or ai_provider.transport())(
                body,
                api_key=ai_provider.api_key(),
                api_base=ai_provider.api_base(),
                timeout=float(settings.ai_report_timeout_seconds),
            )
            raw = parse_json(reply)
            if raw is not None:
                break
            logger.info("[POLICY-AI] reply was not valid JSON; retrying once")
    except Exception as exc:  # noqa: BLE001 - never fail an audit over this
        logger.info("[POLICY-AI] request failed: %s: %s", type(exc).__name__, str(exc)[:160])
        return None
    if raw is None:
        logger.info("[POLICY-AI] reply was not usable")
        return None
    result = validate(raw, clipped, fact_ids(facts))
    cited = {e for issue in result["issues"] for e in issue["evidence_ids"]}
    result["evidence"] = [{"id": f.id, "text": f.text} for f in facts if f.id in cited]
    result.update(
        {
            "status": "analyzed",
            "source": source,
            "chars_read": len(clipped),
            "truncated": truncated,
            "model": ai_provider.model(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result
