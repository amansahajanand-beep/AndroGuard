from __future__ import annotations

from pathlib import Path

from app.db.repository import CONTENT_TYPES, get_screenshot
from app.storage.local import LocalTempStorage
from app.storage.s3 import download_bytes as s3_download


def read_local_screenshots(job_id: str, file_names: list[str], storage: LocalTempStorage) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in file_names:
        path = storage.screenshot_path(job_id, name)
        if path.is_file():
            files[name] = path.read_bytes()
    return files


def load_screenshot(job_id: str, file_name: str, storage: LocalTempStorage) -> tuple[bytes, str] | None:
    path = storage.screenshot_path(job_id, file_name)
    if path.is_file():
        suffix = Path(file_name).suffix.lstrip(".").lower()
        return path.read_bytes(), CONTENT_TYPES.get(suffix, "application/octet-stream")
    from_s3 = s3_download(job_id, file_name)
    if from_s3 is not None:
        return from_s3
    return get_screenshot(job_id, file_name)
