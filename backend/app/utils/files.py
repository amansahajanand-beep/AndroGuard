from __future__ import annotations

import re
import uuid
from pathlib import Path

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def new_job_id() -> str:
    return str(uuid.uuid4())


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def safe_filename(name: str, fallback: str = "file.bin") -> str:
    base = Path(name.replace("\\", "/")).name
    if not base or base in {".", ".."}:
        return fallback
    cleaned = SAFE_NAME.sub("_", base).strip("._")
    return cleaned or fallback


def is_safe_zip_entry(name: str) -> bool:
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        return False
    parts = normalized.split("/")
    return ".." not in parts
