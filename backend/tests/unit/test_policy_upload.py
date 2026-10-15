import asyncio
import io

from fastapi import UploadFile

from app.api.v1.analyze import _build_submission, read_policy_upload
from app.services.ai_report import _policy_analysis
from app.schemas.analysis import AppSubmission


def upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_no_upload_means_no_text_and_no_error() -> None:
    assert asyncio.run(read_policy_upload(None)) == (None, None)


def test_text_upload_is_read() -> None:
    text, error = asyncio.run(read_policy_upload(upload("policy.txt", b"We collect your location. " * 20)))
    assert error is None and text.startswith("We collect")


def test_unreadable_upload_reports_why() -> None:
    text, error = asyncio.run(read_policy_upload(upload("policy.bin", b"\x00\x01")))
    assert text is None and "Unsupported" in error


def test_policy_text_never_appears_in_the_stored_submission() -> None:
    submission = _build_submission("App", "Desc", "policy.txt", None, "secret policy body " * 50, None)
    assert submission.privacy_policy_text
    dumped = submission.model_dump()
    assert "privacy_policy_text" not in dumped and "privacy_policy_error" not in dumped


class _Response:
    def __init__(self, submission: AppSubmission) -> None:
        self.data = type("D", (), {"submission": submission})()


def test_policy_file_name_alone_explains_what_to_do() -> None:
    result = _policy_analysis(_Response(AppSubmission(privacy_policy="policy.pdf")), [], None)
    assert result["status"] == "unavailable" and "upload" in result["reason"].lower()


def test_missing_policy_is_reported() -> None:
    result = _policy_analysis(_Response(AppSubmission()), [], None)
    assert result["status"] == "no_policy"


def test_upload_error_is_passed_through() -> None:
    result = _policy_analysis(_Response(AppSubmission(privacy_policy="p.pdf")), [], None, "PDF policies need the pypdf package on the server.")
    assert result == {"status": "unavailable", "reason": "PDF policies need the pypdf package on the server."}
