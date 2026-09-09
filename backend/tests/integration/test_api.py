import io
import zipfile

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "analyzer_version" in body
    assert body["database"]["configured"] is False
    assert "aapt_available" in body
    assert body["dex_analysis_enabled"] is True


def test_history_without_database(client: TestClient) -> None:
    response = client.get("/api/v1/analyses")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_empty_upload(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("empty.apk", b"", "application/vnd.android.package-archive")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_non_apk_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_random_bytes_named_apk(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("fake.apk", b"not-an-apk", "application/vnd.android.package-archive")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_APK"


def test_zip_without_manifest(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("res/values/strings.xml", "<resources/>")
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("nomamifest.apk", buffer.getvalue(), "application/vnd.android.package-archive")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_APK"
