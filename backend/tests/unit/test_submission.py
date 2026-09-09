import pytest
from pydantic import ValidationError

from app.schemas.analysis import AnalysisData, AppSubmission

MINIMAL_DATA = {
    "apk": {"file_name": "sample.apk", "file_size": 1024, "sha256": "a" * 64},
    "manifest": {},
    "sdk": {},
    "analysis": {
        "status": "completed",
        "analyzed_at": "2026-01-01T00:00:00+00:00",
        "analyzer_version": "1.0.0",
        "duration_ms": 5,
    },
}


def test_defaults_are_empty() -> None:
    submission = AppSubmission()
    assert submission.app_name is None
    assert submission.app_description is None
    assert submission.privacy_policy is None
    assert submission.privacy_policy_kind is None
    assert submission.play_store_url is None


def test_blank_and_whitespace_become_none() -> None:
    submission = AppSubmission(app_name="   ", app_description="", play_store_url="  ")
    assert submission.app_name is None
    assert submission.app_description is None
    assert submission.play_store_url is None


def test_values_are_trimmed() -> None:
    submission = AppSubmission(app_name="  Photo Editor  ", app_description=" Edits photos. ")
    assert submission.app_name == "Photo Editor"
    assert submission.app_description == "Edits photos."


def test_privacy_policy_url_is_classified() -> None:
    submission = AppSubmission(privacy_policy="https://example.com/privacy")
    assert submission.privacy_policy_kind == "url"


def test_privacy_policy_path_is_classified() -> None:
    submission = AppSubmission(privacy_policy="docs/privacy-policy.pdf")
    assert submission.privacy_policy_kind == "file_path"


def test_play_store_url_must_be_http() -> None:
    with pytest.raises(ValidationError):
        AppSubmission(play_store_url="market://details?id=com.example")


def test_app_name_length_is_capped() -> None:
    with pytest.raises(ValidationError):
        AppSubmission(app_name="x" * 201)


def test_analysis_data_defaults_to_empty_submission() -> None:
    data = AnalysisData.model_validate(MINIMAL_DATA)
    assert data.model_dump()["submission"] == {
        "app_name": None,
        "app_description": None,
        "privacy_policy": None,
        "privacy_policy_kind": None,
        "play_store_url": None,
    }


def test_analysis_data_keeps_submitted_values() -> None:
    submission = AppSubmission(
        app_name="Photo Editor",
        app_description="Edits photos.",
        privacy_policy="https://example.com/privacy",
        play_store_url="https://play.google.com/store/apps/details?id=com.example",
    )
    data = AnalysisData.model_validate({**MINIMAL_DATA, "submission": submission.model_dump()})
    dumped = data.model_dump()["submission"]
    assert dumped["app_name"] == "Photo Editor"
    assert dumped["privacy_policy_kind"] == "url"
    assert dumped["play_store_url"].startswith("https://play.google.com/")
