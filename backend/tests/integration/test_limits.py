import io
import time
import zipfile

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.errors import AppError


def test_apk_too_large(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_apk_size_mb", 0)
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("big.apk", b"PK\x03\x04" + b"x" * 64, "application/vnd.android.package-archive")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "APK_TOO_LARGE"


def test_analysis_timeout(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "analysis_timeout_seconds", 0.01)

    def _slow(*_args, **_kwargs):
        time.sleep(0.2)
        raise AssertionError("analyze_apk should have been cancelled by timeout")

    monkeypatch.setattr("app.api.v1.analyze.analyze_apk", _slow)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"not-binary-axml")
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("slow.apk", buffer.getvalue(), "application/vnd.android.package-archive")},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ANALYSIS_TIMEOUT"


def test_aab_is_unsupported(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BundleConfig.pb", b"bundle")
        archive.writestr("base/manifest/AndroidManifest.xml", b"x")
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("app.apk", buffer.getvalue(), "application/vnd.android.package-archive")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_APK"


def test_corrupt_manifest_zip(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"not a binary android manifest")
    response = client.post(
        "/api/v1/analyze",
        files={"file": ("badmanifest.apk", buffer.getvalue(), "application/vnd.android.package-archive")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"CORRUPT_APK", "MANIFEST_INVALID"}


def test_unknown_file_404(client: TestClient) -> None:
    response = client.get("/api/v1/files/11111111-1111-1111-1111-111111111111/missing.png")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INVALID_FILE"
