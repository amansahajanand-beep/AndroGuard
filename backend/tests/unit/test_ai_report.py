import json

from app.core.config import settings
from app.services.ai_report import attach_ai_review, generate_ai_review, parse_review
from app.services.audit_evidence import build_facts, fact_ids

RESULT = {
    "data": {
        "apk": {"package_name": "com.fitpal.tracker", "version_name": "3.2.1"},
        "sdk": {"target_sdk": 33},
        "submission": {"app_name": "FitPal", "app_description": "Workout tracker", "privacy_policy": None},
        "permissions": [{"name": "android.permission.READ_CONTACTS"}, {"name": "android.permission.CAMERA"}],
        "code_analysis": {"third_party_sdk_usage": [{"name": "Google AdMob"}], "network_calls": [1, 2, 3]},
        "exploration": {
            "status": "completed",
            "states": [{}, {}],
            "ad_timeline": [
                {
                    "page": "HomeActivity",
                    "positions_seen": ["bottom", "top"],
                    "position_changed": True,
                    "sightings": [{"ad_type": "banner"}],
                }
            ],
        },
    }
}


def reply(findings, summary="FitPal targets SDK 33 and reads contacts."):
    return json.dumps({"summary": summary, "findings": findings, "ad_notes": "Banner moved top."})


def enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", "k")


def test_fact_sheet_has_stable_ids_and_plain_facts() -> None:
    facts = {f.id: f.text for f in build_facts(RESULT)}
    assert "perm:READ_CONTACTS" in facts and "sdk:google-admob" in facts
    assert "advertising SDK" in facts["sdk:google-admob"]
    assert facts["code:network_calls"] == "The code contains 3 network calls."
    assert "changed" in facts["ad:1"]
    assert "No privacy policy" in facts["policy:provided"]


def test_findings_without_valid_citations_are_dropped() -> None:
    known = fact_ids(build_facts(RESULT))
    review = parse_review(
        reply(
            [
                {"title": "Contacts", "severity": "HIGH", "evidence_ids": ["perm:READ_CONTACTS"]},
                {"title": "Made up", "severity": "high", "evidence_ids": ["perm:RECORD_AUDIO"]},
                {"title": "No citation", "severity": "low", "evidence_ids": []},
                {"title": "", "severity": "low", "evidence_ids": ["perm:CAMERA"]},
                {"title": "Odd severity", "severity": "catastrophic", "evidence_ids": ["perm:CAMERA", "bogus"]},
            ]
        ),
        known,
    )
    titles = [f["title"] for f in review["findings"]]
    assert titles == ["Contacts", "Odd severity"]
    assert review["findings"][0]["severity"] == "high"
    assert review["findings"][1]["severity"] == "medium"
    assert review["findings"][1]["evidence_ids"] == ["perm:CAMERA"]
    assert review["unsupported_dropped"] == 3


def test_parse_rejects_missing_summary_and_garbage() -> None:
    assert parse_review('{"findings": []}') is None
    assert parse_review("nothing") is None


def test_disabled_or_keyless_makes_no_call(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(settings, "ai_report_enabled", False)
    assert generate_ai_review(RESULT, transport=lambda *a, **k: called.append(1) or "") is None
    monkeypatch.setattr(settings, "ai_report_enabled", True)
    monkeypatch.setattr(settings, "ai_report_api_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    assert generate_ai_review(RESULT, transport=lambda *a, **k: called.append(1) or "") is None
    assert not called


def test_review_includes_only_cited_evidence_and_sends_the_fact_sheet(monkeypatch) -> None:
    enable(monkeypatch)
    seen = {}

    def fake(body, **kwargs):
        seen["body"] = body
        return reply([{"title": "Contacts", "severity": "high", "evidence_ids": ["perm:READ_CONTACTS"]}])

    review = generate_ai_review(RESULT, transport=fake)
    assert [e["id"] for e in review["evidence"]] == ["perm:READ_CONTACTS"]
    assert review["disclaimer"] and review["generated_at"] and review["model"]
    sent = seen["body"]["messages"][0]["content"]
    assert "perm:READ_CONTACTS:" in sent and seen["body"]["temperature"] == 0


def test_failure_returns_none(monkeypatch) -> None:
    enable(monkeypatch)

    def boom(*a, **k):
        raise OSError("down")

    assert generate_ai_review(RESULT, transport=boom) is None


def test_attach_does_nothing_when_ai_is_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_report_enabled", False)

    class Boom:
        def model_dump(self):
            raise AssertionError("must not be touched")

    attach_ai_review(Boom())
