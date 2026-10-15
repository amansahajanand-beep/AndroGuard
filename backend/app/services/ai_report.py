"""AI-written review of an audit, grounded in a numbered fact sheet.

The rule-based report stays the source of truth for verdicts. This adds a plain-language
summary and per-risk explanations under ``data.ai_review``, plus a privacy-policy comparison
under ``data.ai_policy_analysis``. The model sees only the fact sheet built from the audit's
own JSON, and every finding must cite fact ids from it. Findings that cite nothing, or cite
ids that do not exist, are dropped and counted. Every failure returns ``None``; an audit never
fails because the review could not be written.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from app.core.config import settings
from app.services import ai_provider
from app.services.audit_evidence import Fact, build_facts, fact_ids, render_facts

logger = logging.getLogger(__name__)

SEVERITIES = ("critical", "high", "medium", "low")
DISCLAIMER = (
    "AI-generated from the facts found in this audit; each finding cites those facts. It explains and "
    "prioritises findings, does not change the rule-based verdicts, and does not replace Google Play Console review."
)

SYSTEM_PROMPT = (
    "You review Android app audits for Google Play compliance. You receive a numbered fact sheet extracted "
    "from a static APK analysis and an automated emulator run. Use ONLY those facts. Do not invent "
    "permissions, SDKs, screens or ads. If the facts are thin, say so. "
    "Every finding MUST list the fact ids it relies on in evidence_ids; a finding without valid ids is discarded. "
    "Reply with JSON only: "
    '{"summary": "<=110 words, plain language, for a product owner", '
    '"findings": [{"title": "", "severity": "critical|high|medium|low", '
    '"explanation": "why this matters for Play policy", "evidence_ids": ["fact id"], '
    '"recommended_fix": "concrete next step"}], '
    '"ad_notes": "<=60 words on ad placements seen, or empty"}. '
    "At most 6 findings, most important first."
)


def parse_review(text: str, known_fact_ids: set[str] | None = None) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    summary = str(raw.get("summary") or "").strip()
    if not summary:
        return None
    findings: list[dict[str, Any]] = []
    dropped = 0
    for item in (raw.get("findings") or [])[:6]:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            dropped += 1
            continue
        evidence = [e for e in (item.get("evidence_ids") or []) if isinstance(e, str)]
        if known_fact_ids is not None:
            evidence = [e for e in evidence if e in known_fact_ids]
            if not evidence:
                dropped += 1
                continue
        severity = str(item.get("severity") or "medium").lower()
        findings.append(
            {
                "title": str(item["title"]).strip()[:140],
                "severity": severity if severity in SEVERITIES else "medium",
                "explanation": str(item.get("explanation") or "").strip()[:600],
                "evidence_ids": evidence,
                "recommended_fix": str(item.get("recommended_fix") or "").strip()[:400],
            }
        )
    return {
        "summary": summary[:900],
        "findings": findings,
        "ad_notes": str(raw.get("ad_notes") or "").strip()[:400],
        "unsupported_dropped": dropped,
    }


def generate_ai_review(
    result: dict[str, Any],
    *,
    facts: list[Fact] | None = None,
    transport: Callable[..., str] | None = None,
) -> dict[str, Any] | None:
    if not ai_provider.configured():
        return None
    facts = facts if facts is not None else build_facts(result)
    try:
        body = {
            "model": ai_provider.model(),
            "max_tokens": 1400,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": "Facts:\n" + render_facts(facts)}],
        }
        review = None
        for _attempt in range(2):
            text = (transport or ai_provider.transport())(
                body,
                api_key=ai_provider.api_key(),
                api_base=ai_provider.api_base(),
                timeout=float(settings.ai_report_timeout_seconds),
            )
            review = parse_review(text, fact_ids(facts))
            if review is not None:
                break
            logger.info("[AI-REPORT] reply was not valid JSON; retrying once")
    except Exception as exc:  # noqa: BLE001 - never fail an audit over the review
        logger.info("[AI-REPORT] request failed: %s: %s", type(exc).__name__, str(exc)[:160])
        return None
    if review is None:
        logger.info("[AI-REPORT] model reply was not usable")
        return None
    cited = {e for f in review["findings"] for e in f["evidence_ids"]}
    review["evidence"] = [{"id": f.id, "text": f.text} for f in facts if f.id in cited]
    review["model"] = ai_provider.model()
    review["generated_at"] = datetime.now(timezone.utc).isoformat()
    review["disclaimer"] = DISCLAIMER
    return review


def _policy_analysis(
    response: Any, facts: list[Fact], policy_text: str | None, policy_error: str | None = None
) -> dict[str, Any] | None:
    from app.services.policy_analysis import analyze_policy
    from app.services.policy_text import fetch_policy_text

    submission = response.data.submission
    reference = (submission.privacy_policy or "") if submission else ""
    source = "upload"
    if policy_text is None and policy_error:
        return {"status": "unavailable", "reason": policy_error}
    if policy_text is None:
        if not reference:
            return {"status": "no_policy", "reason": "No privacy policy was provided, so nothing could be compared."}
        if not reference.lower().startswith(("http://", "https://")):
            return {
                "status": "unavailable",
                "reason": "The policy was given as a file name only; upload the file or give a link to compare it.",
            }
        text, error = fetch_policy_text(reference)
        if text is None:
            return {"status": "unavailable", "reason": error or "The privacy policy could not be read."}
        policy_text, source = text, "url"
    analysis = analyze_policy(policy_text, facts, source=source)
    return analysis


def attach_ai_review(
    response: Any, *, policy_text: str | None = None, policy_error: str | None = None
) -> None:
    """Add ``data.ai_review`` and ``data.ai_policy_analysis`` to an AnalysisResponse in place (best effort)."""
    if not settings.ai_report_enabled:
        return
    facts: list[Fact] = []
    try:
        result = response.model_dump()
        facts = build_facts(result)
        review = generate_ai_review(result, facts=facts)
        if review is not None:
            response.data.ai_review = review
    except Exception:  # noqa: BLE001
        logger.exception("[AI-REPORT] could not attach review")
        facts = []
    try:
        analysis = _policy_analysis(response, facts, policy_text, policy_error)
        if analysis is not None:
            response.data.ai_policy_analysis = analysis
    except Exception:  # noqa: BLE001
        logger.exception("[POLICY-AI] could not attach policy analysis")
