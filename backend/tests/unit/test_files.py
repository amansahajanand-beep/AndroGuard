from app.storage.images import read_local_screenshots
from app.storage.local import LocalTempStorage
from app.utils.files import is_safe_zip_entry, safe_filename


def test_safe_filename_strips_paths() -> None:
    assert safe_filename("../etc/passwd") == "passwd"
    assert safe_filename("res/mipmap/ic_launcher.png") == "ic_launcher.png"


def test_zip_slip_rejected() -> None:
    assert is_safe_zip_entry("../secret.png") is False
    assert is_safe_zip_entry("/abs/path.png") is False
    assert is_safe_zip_entry("res/mipmap/ic_launcher.png") is True


def test_read_local_screenshots(tmp_path) -> None:
    storage = LocalTempStorage(root=tmp_path)
    job_id = "11111111-1111-1111-1111-111111111111"
    path = storage.screenshot_path(job_id, "icon.png")
    path.write_bytes(b"\x89PNG")
    files = read_local_screenshots(job_id, ["icon.png", "missing.png"], storage)
    assert files["icon.png"] == b"\x89PNG"
    assert "missing.png" not in files
