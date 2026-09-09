from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.modules.apk_analyzer.context import ApkContext
from app.storage.local import LocalTempStorage
from app.utils.files import is_safe_zip_entry, safe_filename
from app.utils.hashing import sha256_bytes

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PATH_PREFIXES = ("res/drawable", "res/mipmap", "assets/")


def _is_candidate(name: str) -> bool:
    lowered = name.replace("\\", "/").lower()
    suffix = Path(lowered).suffix
    if suffix not in IMAGE_EXTS:
        return False
    return any(lowered.startswith(prefix) for prefix in PATH_PREFIXES)


def _priority(name: str) -> tuple[int, int, str]:
    lowered = name.lower()
    launcher = 0 if "ic_launcher" in lowered or "ic_foreground" in lowered else 1
    mipmap = 0 if "/mipmap" in lowered else 1
    return (launcher, mipmap, lowered)


def extract_screenshots(ctx: ApkContext, storage: LocalTempStorage) -> list[dict]:
    candidates = [name for name in ctx.zip_names if _is_candidate(name) and is_safe_zip_entry(name)]
    candidates.sort(key=_priority)

    results: list[dict] = []
    seen_hashes: set[str] = set()
    used_names: set[str] = set()

    try:
        archive = zipfile.ZipFile(ctx.path)
    except zipfile.BadZipFile:
        ctx.warnings.append("Could not reopen APK to extract images.")
        return []

    with archive:
        for entry_name in candidates:
            if len(results) >= settings.max_screenshots:
                ctx.warnings.append("Screenshot extraction stopped at the configured maximum.")
                break
            try:
                info = archive.getinfo(entry_name)
                if info.file_size > settings.max_image_bytes:
                    continue
                data = archive.read(entry_name)
            except Exception:
                continue
            if len(data) > settings.max_image_bytes:
                continue
            digest = sha256_bytes(data)
            if digest in seen_hashes:
                continue
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                    fmt = (image.format or Path(entry_name).suffix.lstrip(".")).lower()
            except (UnidentifiedImageError, OSError):
                continue

            filename = safe_filename(Path(entry_name).name, fallback=f"image_{len(results) + 1}.bin")
            if filename in used_names:
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                filename = f"{stem}_{digest[:8]}{suffix}"
            used_names.add(filename)
            dest = storage.screenshot_path(ctx.job_id, filename)
            dest.write_bytes(data)
            seen_hashes.add(digest)
            results.append(
                {
                    "file_name": filename,
                    "url": f"/api/v1/files/{ctx.job_id}/{filename}",
                    "original_path": entry_name.replace("\\", "/"),
                    "width": width,
                    "height": height,
                    "format": fmt,
                    "byte_size": len(data),
                }
            )
    return results
