import io
import json
import urllib.error
import zipfile

import pytest

from app.core.config import settings
from app.services import policy_text
from app.services.audit_evidence import Fact
from app.services.policy_analysis import analyze_policy, validate
from app.services.policy_text import extract_policy_text, fetch_policy_text, html_to_text

POLICY = (
    "Privacy Policy for FitPal. We collect your approximate location to show nearby workouts. "
    "We do not sell your personal information. We use analytics to improve the app. "
    "You can delete your account at any time from the settings screen. "
) * 3
FACTS = [
    Fact("perm:READ_CONTACTS", "The manifest declares permission android.permission.READ_CONTACTS."),
    Fact("perm:ACCESS_FINE_LOCATION", "The manifest declares permission android.permission.ACCESS_FINE_LOCATION."),
    Fact("sdk:google-admob", "The code uses Google AdMob, an advertising SDK."),
]
IDS = {f.id for f in FACTS}
LOCATION_QUOTE = "We collect your approximate location to show nearby workouts"


def test_claims_need_a_verbatim_quote() -> None:
    raw = {
        "claims": [
            {"topic": "location", "statement": "Collects location", "quote": LOCATION_QUOTE},
            {"topic": "ads", "statement": "Shows ads", "quote": "We display personalised advertising"},
            {"topic": "other", "statement": "short", "quote": "too short"},
        ],
        "issues": [],
    }
    result = validate(raw, POLICY, IDS)
    assert [c["topic"] for c in result["claims"]] == ["location"]
    assert result["unsupported_dropped"] == 2


def test_quote_match_ignores_case_and_whitespace() -> None:
    raw = {"claims": [{"topic": "retention", "statement": "x", "quote": "YOU CAN   delete your\naccount at any time"}], "issues": []}
    assert len(validate(raw, POLICY, set())["claims"]) == 1


def test_behaviour_issues_must_cite_real_facts() -> None:
    raw = {
        "claims": [],
        "issues": [
            {"type": "undisclosed_data_use", "severity": "HIGH", "title": "Contacts not disclosed", "evidence_ids": ["perm:READ_CONTACTS", "perm:FAKE"]},
            {"type": "undisclosed_data_use", "severity": "high", "title": "No evidence", "evidence_ids": ["perm:FAKE"]},
            {"type": "vague_or_missing", "severity": "low", "title": "No retention period", "evidence_ids": []},
            {"type": "made_up_type", "severity": "low", "title": "Bad type", "evidence_ids": ["perm:READ_CONTACTS"]},
        ],
    }
    issues = validate(raw, POLICY, IDS)["issues"]
    assert [i["title"] for i in issues] == ["Contacts not disclosed", "No retention period"]
    assert issues[0]["evidence_ids"] == ["perm:READ_CONTACTS"] and issues[0]["severity"] == "high"


def test_a_contradiction_needs_a_claim_on_that_topic() -> None:
    claim = {"topic": "location", "statement": "x", "quote": LOCATION_QUOTE}
    issue = {
        "type": "contradiction",
        "severity": "medium",
        "title": "Location precision",
        "evidence_ids": ["perm:ACCESS_FINE_LOCATION"],
        "claim_topics": ["location"],
    }
    ok = validate({"claims": [claim], "issues": [issue]}, POLICY, IDS)
    assert len(ok["issues"]) == 1 and ok["issues"][0]["claim_ids"] == ["c1"]
    assert validate({"claims": [], "issues": [issue]}, POLICY, IDS)["issues"] == []


def test_analyze_policy_end_to_end_with_a_fake_model(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", "k")
    captured = {}

    def fake(body, **kwargs):
        captured["body"] = body
        return json.dumps(
            {
                "summary": "Contacts access is not disclosed.",
                "claims": [{"topic": "location", "statement": "Collects location", "quote": LOCATION_QUOTE}],
                "issues": [
                    {
                        "type": "undisclosed_data_use",
                        "severity": "high",
                        "title": "Contacts",
                        "evidence_ids": ["perm:READ_CONTACTS"],
                        "claim_topics": [],
                        "recommended_fix": "Disclose it.",
                    }
                ],
            }
        )

    result = analyze_policy(POLICY, FACTS, source="url", transport=fake)
    assert result["status"] == "analyzed" and result["source"] == "url" and result["truncated"] is False
    assert len(result["claims"]) == 1 and len(result["issues"]) == 1
    prompt = captured["body"]["messages"][0]["content"]
    assert "perm:READ_CONTACTS:" in prompt and "Privacy Policy for FitPal" in prompt
    assert captured["body"]["temperature"] == 0


def test_long_policies_are_truncated_and_flagged(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", "k")
    monkeypatch.setattr(settings, "ai_policy_max_chars", 300)
    empty = lambda *a, **k: json.dumps({"summary": "s", "claims": [], "issues": []})  # noqa: E731
    result = analyze_policy(POLICY * 5, FACTS, source="upload", transport=empty)
    assert result["truncated"] is True and result["chars_read"] == 300


def test_disabled_makes_no_call(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", False)
    assert analyze_policy(POLICY, FACTS, source="url", transport=lambda *a, **k: "x") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/policy",
        "http://localhost/policy",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/p",
        "ftp://example.com/p",
        "file:///etc/passwd",
    ],
)
def test_fetch_refuses_non_public_and_non_http_targets(url) -> None:
    text, error = fetch_policy_text(url)
    assert text is None and error


def test_html_is_reduced_to_readable_text() -> None:
    markup = "<html><head><title>x</title></head><body><script>bad()</script><h1>Privacy</h1><p>We collect  data.</p></body></html>"
    text = html_to_text(markup)
    assert "Privacy" in text and "We collect data." in text and "bad()" not in text


def test_extract_txt_html_and_unsupported() -> None:
    body = ("We collect your location. " * 20).encode()
    assert extract_policy_text("policy.txt", body)[0].startswith("We collect")
    assert extract_policy_text("policy.html", b"<p>" + body + b"</p>")[0].startswith("We collect")
    text, error = extract_policy_text("policy.exe", b"x")
    assert text is None and "Unsupported" in error
    text, error = extract_policy_text("tiny.txt", b"hi")
    assert text is None and "too little" in error


def test_extract_docx() -> None:
    xml = "<w:document><w:p><w:t>" + "We never sell data. " * 20 + "</w:t></w:p></w:document>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    text, error = extract_policy_text("policy.docx", buffer.getvalue())
    assert error is None and "never sell data" in text


def test_redirects_are_rechecked(monkeypatch) -> None:
    calls = []

    class Opener:
        def open(self, request, timeout=0):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 302, "found", {"Location": "http://127.0.0.1/admin"}, None)

    monkeypatch.setattr(policy_text, "_host_is_public", lambda host: host != "127.0.0.1")
    monkeypatch.setattr(policy_text.urllib.request, "build_opener", lambda *a: Opener())
    text, error = fetch_policy_text("http://example.com/policy")
    assert text is None and "not a public address" in error
    assert calls == ["http://example.com/policy"]


# ---- code-level guards against false alarms (found by running the live eval) ---------------------

DISCLOSING_POLICY = (
    "We collect your approximate location to show nearby workouts. With your permission we read your contacts "
    "to invite friends. We use Google AdMob to show advertising and analytics to improve the app. " * 2
)
ALL_FACTS = {
    "perm:ACCESS_COARSE_LOCATION", "perm:READ_CONTACTS", "perm:RECORD_AUDIO", "sdk:google-admob", "code:network_calls",
}


def issue(title, evidence, kind="undisclosed_data_use", severity="high"):
    return {"type": kind, "severity": severity, "title": title, "evidence_ids": evidence, "claim_topics": []}


def test_generic_code_facts_cannot_back_undisclosed_data_use() -> None:
    result = validate({"claims": [], "issues": [issue("Network calls", ["code:network_calls"])]}, POLICY, ALL_FACTS)
    assert result["issues"] == [] and result["unsupported_dropped"] == 1


def test_topics_the_policy_mentions_are_not_reported_as_undisclosed() -> None:
    raw = {"claims": [], "issues": [
        issue("Location", ["perm:ACCESS_COARSE_LOCATION"]),
        issue("Contacts", ["perm:READ_CONTACTS"]),
        issue("Ads", ["sdk:google-admob"]),
    ]}
    result = validate(raw, DISCLOSING_POLICY, ALL_FACTS)
    assert result["issues"] == [] and result["unsupported_dropped"] == 3


def test_a_topic_the_policy_never_mentions_is_still_reported() -> None:
    result = validate({"claims": [], "issues": [issue("Microphone", ["perm:RECORD_AUDIO"])]}, DISCLOSING_POLICY, ALL_FACTS)
    assert [i["title"] for i in result["issues"]] == ["Microphone"]


def test_mixed_evidence_keeps_only_data_facts_and_still_checks_coverage() -> None:
    raw = {"claims": [], "issues": [issue("Mic + network", ["code:network_calls", "perm:RECORD_AUDIO"])]}
    issues = validate(raw, DISCLOSING_POLICY, ALL_FACTS)["issues"]
    assert issues[0]["evidence_ids"] == ["perm:RECORD_AUDIO"]


def test_vague_issues_are_capped_and_never_high() -> None:
    raw = {"claims": [], "issues": [
        issue("A", [], "vague_or_missing", "high"), issue("B", [], "vague_or_missing", "medium"), issue("C", [], "vague_or_missing", "low"),
    ]}
    issues = validate(raw, POLICY, ALL_FACTS)["issues"]
    assert [i["title"] for i in issues] == ["A", "B"] and issues[0]["severity"] == "medium"


def test_claim_ids_still_link_after_the_guards() -> None:
    claim = {"topic": "ads", "statement": "Ad-free", "quote": "FitPal is an ad-free app and never shows advertising"}
    policy = "FitPal is an ad-free app and never shows advertising. " * 6
    raw = {"claims": [claim], "issues": [{"type": "contradiction", "severity": "high", "title": "Ads present", "evidence_ids": ["sdk:google-admob"], "claim_topics": ["ads"]}]}
    issues = validate(raw, policy, ALL_FACTS)["issues"]
    assert len(issues) == 1 and issues[0]["claim_ids"] == ["c1"]


def test_an_unparseable_reply_is_retried_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", "k")
    replies = iter(['{"summary": "broken', json.dumps({"summary": "fine", "claims": [], "issues": []})])
    result = analyze_policy(POLICY, FACTS, source="url", transport=lambda *a, **k: next(replies))
    assert result is not None and result["summary"] == "fine"


def test_two_unparseable_replies_give_up_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", "k")
    assert analyze_policy(POLICY, FACTS, source="url", transport=lambda *a, **k: "not json at all") is None
