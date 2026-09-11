from __future__ import annotations

import time

from fastapi.testclient import TestClient

APK_MIME = "application/vnd.android.package-archive"
TERMINAL = {"completed", "failed", "cancelled", "timeout", "partial"}


def _poll(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    """Wait for the background worker to reach a terminal state."""
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analyze-apk/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.2)
    raise AssertionError(f"Job {job_id} did not finish; last state: {body}")


def test_rejects_non_apk_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze-apk",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_rejects_empty_upload(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze-apk",
        files={"file": ("empty.apk", b"", APK_MIME)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_missing_file_returns_invalid_file(client: TestClient) -> None:
    response = client.post("/api/v1/analyze-apk", data={"app_name": "x"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_accepted_upload_returns_job_id_immediately(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze-apk",
        files={"file": ("fake.apk", b"not-an-apk", APK_MIME)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["job_id"]
    assert body["status"] == "processing"
    assert body["status_url"].endswith(body["job_id"])


def test_job_reports_failure_for_invalid_apk(client: TestClient) -> None:
    created = client.post(
        "/api/v1/analyze-apk",
        files={"file": ("fake.apk", b"not-an-apk", APK_MIME)},
    ).json()
    body = _poll(client, created["job_id"])
    assert body["status"] == "failed"
    assert body["error"]["code"] == "INVALID_APK"
    assert body["progress"] >= 0


def test_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyze-apk/2ea64a01-f641-4acd-87c0-3958140c934c")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_malformed_job_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyze-apk/not-a-uuid")
    assert response.status_code == 404


def test_existing_sync_endpoint_still_works(client: TestClient) -> None:
    """The original endpoint must keep its synchronous contract."""
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("fake.apk", b"not-an-apk", APK_MIME)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_APK"
    assert "job_id" not in response.json()
