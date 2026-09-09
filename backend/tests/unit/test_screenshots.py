from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

from app.core.config import settings
from app.modules.screenshots.extract import extract_screenshots
from app.storage.local import LocalTempStorage
from tests.fixtures.images import raster_bytes


def _ctx(path, names):
    return SimpleNamespace(path=path, zip_names=names, job_id=str(uuid4()), warnings=[])


def test_extracts_png_jpeg_webp(tmp_path) -> None:
    apk = tmp_path / "sample.apk"
    png = raster_bytes("PNG")
    jpeg = raster_bytes("JPEG")
    webp = raster_bytes("WEBP")
    with ZipFile(apk, "w") as archive:
        archive.writestr("res/mipmap-xxhdpi/ic_launcher.png", png)
        archive.writestr("res/drawable-hdpi/photo.jpg", jpeg)
        archive.writestr("assets/banner.webp", webp)
        archive.writestr("res/layout/activity_main.xml", "<xml/>")
    storage = LocalTempStorage(root=tmp_path / "jobs")
    names = [
        "res/mipmap-xxhdpi/ic_launcher.png",
        "res/drawable-hdpi/photo.jpg",
        "assets/banner.webp",
        "res/layout/activity_main.xml",
    ]
    results = extract_screenshots(_ctx(apk, names), storage)
    formats = {item["format"] for item in results}
    assert formats == {"png", "jpeg", "webp"}
    assert any(item["file_name"] == "ic_launcher.png" for item in results)
    assert all(item["width"] == 16 and item["height"] == 16 for item in results)


def test_zip_slip_entries_are_skipped(tmp_path) -> None:
    apk = tmp_path / "slip.apk"
    png = raster_bytes("PNG")
    with ZipFile(apk, "w") as archive:
        archive.writestr("../secret.png", png)
        archive.writestr("res/mipmap/ic_launcher.png", png)
    storage = LocalTempStorage(root=tmp_path / "jobs")
    names = ["../secret.png", "res/mipmap/ic_launcher.png"]
    results = extract_screenshots(_ctx(apk, names), storage)
    assert [item["original_path"] for item in results] == ["res/mipmap/ic_launcher.png"]


def test_screenshot_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_screenshots", 1)
    apk = tmp_path / "many.apk"
    png = raster_bytes("PNG")
    names = [
        "res/drawable/one.png",
        "res/drawable/two.png",
        "res/drawable/three.png",
    ]
    with ZipFile(apk, "w") as archive:
        for name in names:
            archive.writestr(name, png)
    storage = LocalTempStorage(root=tmp_path / "jobs")
    ctx = _ctx(apk, names)
    results = extract_screenshots(ctx, storage)
    assert len(results) == 1
    assert any("maximum" in warning for warning in ctx.warnings)


def test_duplicate_bytes_are_deduped(tmp_path) -> None:
    apk = tmp_path / "dup.apk"
    png = raster_bytes("PNG")
    with ZipFile(apk, "w") as archive:
        archive.writestr("res/drawable-mdpi/icon.png", png)
        archive.writestr("res/drawable-hdpi/icon.png", png)
    storage = LocalTempStorage(root=tmp_path / "jobs")
    names = ["res/drawable-mdpi/icon.png", "res/drawable-hdpi/icon.png"]
    results = extract_screenshots(_ctx(apk, names), storage)
    assert len(results) == 1
