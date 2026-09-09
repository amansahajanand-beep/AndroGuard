from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.errors import AppError

ReadChunk = Callable[[int], Awaitable[bytes]]


async def stream_to_file(
    read: ReadChunk,
    dest: Path,
    max_bytes: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    too_large = False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        while True:
            chunk = await read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                too_large = True
                break
            digest.update(chunk)
            handle.write(chunk)
    if too_large:
        dest.unlink(missing_ok=True)
        raise AppError(
            "APK_TOO_LARGE",
            "The uploaded APK exceeds the maximum allowed size.",
            http_status=413,
        )
    if size == 0:
        dest.unlink(missing_ok=True)
        raise AppError("INVALID_FILE", "The uploaded file is empty.")
    return size, digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
