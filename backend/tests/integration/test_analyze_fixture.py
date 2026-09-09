from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "apks" / "sample.apk"


@pytest.mark.skipif(not FIXTURE.is_file(), reason="sample.apk fixture is not present")
def test_analyze_sample_apk(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("sample.apk", FIXTURE.read_bytes(), "application/vnd.android.package-archive")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0.0"
    assert body["status"] == "completed"
    assert body["data"]["apk"]["sha256"]
    assert "manifest" in body["data"]
    assert "permissions" in body["data"]
    assert "sdk" in body["data"]
    assert "activities" in body["data"]
    assert "services" in body["data"]
    assert "screenshots" in body["data"]
    assert "code_analysis" in body["data"]
    assert "sensitive_api_calls" in body["data"]["code_analysis"]
    assert "api_calls" in body["data"]["code_analysis"]
