from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings
from app.db.repository import CONTENT_TYPES

logger = logging.getLogger(__name__)


def object_key(job_id: str, file_name: str) -> str:
    return f"{job_id}/{file_name}"


def public_url(job_id: str, file_name: str) -> str:
    key = object_key(job_id, file_name)
    base = (settings.s3_public_base_url or "").rstrip("/")
    if not base:
        endpoint = (settings.s3_endpoint_url or "").rstrip("/")
        base = endpoint.replace("/storage/v1/s3", "/storage/v1/object/public")
    return f"{base}/{settings.s3_bucket}/{quote(key)}"


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )


def s3_ready() -> bool:
    if not settings.s3_enabled:
        return False
    try:
        _client().head_bucket(Bucket=settings.s3_bucket)
        return True
    except Exception:
        try:
            _client().create_bucket(Bucket=settings.s3_bucket)
            return True
        except Exception:
            logger.warning("S3 bucket check failed", exc_info=True)
            return False


def upload_bytes(job_id: str, file_name: str, data: bytes, fmt: str | None) -> str:
    content_type = CONTENT_TYPES.get((fmt or "").lower(), "application/octet-stream")
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=object_key(job_id, file_name),
        Body=data,
        ContentType=content_type,
    )
    return public_url(job_id, file_name)


def download_bytes(job_id: str, file_name: str) -> tuple[bytes, str] | None:
    if not settings.s3_enabled:
        return None
    try:
        response = _client().get_object(
            Bucket=settings.s3_bucket,
            Key=object_key(job_id, file_name),
        )
        body = response["Body"].read()
        content_type = response.get("ContentType") or "application/octet-stream"
        return body, content_type
    except Exception:
        return None


def upload_screenshots(job_id: str, files: dict[str, bytes], formats: dict[str, str | None]) -> dict[str, str]:
    urls: dict[str, str] = {}
    if not settings.s3_enabled or not files:
        return urls
    if not s3_ready():
        raise RuntimeError("S3 bucket is not reachable.")
    for name, data in files.items():
        urls[name] = upload_bytes(job_id, name, data, formats.get(name))
    return urls


# --- Prefixed keys -----------------------------------------------------------
# Emulator captures are stored under their own prefix so they never collide with
# the existing "{job_id}/{file_name}" keys used for APK image assets.


def prefixed_key(prefix: str, job_id: str, file_name: str) -> str:
    clean = (prefix or "").strip("/")
    return f"{clean}/{job_id}/{file_name}" if clean else f"{job_id}/{file_name}"


def prefixed_public_url(prefix: str, job_id: str, file_name: str) -> str:
    key = prefixed_key(prefix, job_id, file_name)
    base = (settings.s3_public_base_url or "").rstrip("/")
    if not base:
        endpoint = (settings.s3_endpoint_url or "").rstrip("/")
        base = endpoint.replace("/storage/v1/s3", "/storage/v1/object/public")
    return f"{base}/{settings.s3_bucket}/{quote(key)}"


def upload_prefixed_bytes(
    prefix: str,
    job_id: str,
    file_name: str,
    data: bytes,
    fmt: str | None = None,
) -> tuple[str, str]:
    """Upload one object under ``prefix``. Returns ``(key, public_url)``."""
    key = prefixed_key(prefix, job_id, file_name)
    content_type = CONTENT_TYPES.get((fmt or "").lower(), "application/octet-stream")
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key, prefixed_public_url(prefix, job_id, file_name)


def download_prefixed_bytes(prefix: str, job_id: str, file_name: str) -> tuple[bytes, str] | None:
    if not settings.s3_enabled:
        return None
    try:
        response = _client().get_object(
            Bucket=settings.s3_bucket,
            Key=prefixed_key(prefix, job_id, file_name),
        )
        body = response["Body"].read()
        return body, response.get("ContentType") or "application/octet-stream"
    except Exception:
        return None


def upload_exploration_screenshots(
    job_id: str,
    files: dict[str, bytes],
    formats: dict[str, str | None] | None = None,
) -> dict[str, tuple[str, str]]:
    """Upload emulator captures. Returns ``{file_name: (key, url)}``."""
    results: dict[str, tuple[str, str]] = {}
    if not settings.s3_enabled or not files:
        return results
    if not s3_ready():
        raise RuntimeError("S3 bucket is not reachable.")
    prefix = settings.exploration_s3_prefix
    fmt_map = formats or {}
    for name, data in files.items():
        fmt = fmt_map.get(name) or Path(name).suffix.lstrip(".")
        results[name] = upload_prefixed_bytes(prefix, job_id, name, data, fmt)
    return results
