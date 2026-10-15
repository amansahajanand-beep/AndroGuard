from __future__ import annotations

import logging
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings
from app.db.repository import CONTENT_TYPES

logger = logging.getLogger(__name__)


def object_key(job_id: str, file_name: str) -> str:
    return f"{job_id}/{file_name}"


def public_url(job_id: str, file_name: str) -> str:
    return public_url_for_key(object_key(job_id, file_name))


def public_url_for_key(key: str) -> str:
    """Build a public URL for an arbitrary object key (no credentials in logs)."""
    base = (settings.s3_public_base_url or "").rstrip("/")
    if not base:
        endpoint = (settings.s3_endpoint_url or "").rstrip("/")
        if endpoint:
            base = endpoint.replace("/storage/v1/s3", "/storage/v1/object/public")
        else:
            # Standard AWS virtual-host style when no custom public base is set.
            region = settings.s3_region or "us-east-1"
            return f"https://{settings.s3_bucket}.s3.{region}.amazonaws.com/{quote(key)}"
    return f"{base}/{settings.s3_bucket}/{quote(key)}"


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    timeout = max(5.0, float(settings.s3_upload_timeout_seconds or 30.0))
    endpoint = (settings.s3_endpoint_url or "").strip() or None
    cfg = Config(
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={"max_attempts": 1, "mode": "standard"},
        s3={"addressing_style": "path" if endpoint else "auto"},
    )
    kwargs: dict = {
        "service_name": "s3",
        "region_name": settings.s3_region,
        "aws_access_key_id": settings.s3_access_key,
        "aws_secret_access_key": settings.s3_secret_key,
        "config": cfg,
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    # Credentials are passed to boto3 only — never logged.
    return boto3.client(**kwargs)


def reset_s3_client() -> None:
    """Drop the cached client (tests / credential rotation)."""
    _client.cache_clear()


def s3_ready() -> bool:
    # Never skip put_object solely because head_bucket failed — credentials may
    # still allow uploads (common with Supabase / path-style endpoints).
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
            logger.warning(
                "S3 bucket check failed for %s (uploads may still succeed)",
                settings.s3_bucket,
                exc_info=True,
            )
            # Treat as ready-enough when credentials+bucket are configured so
            # callers attempt put_object instead of skipping all screenshots.
            return True


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
    return public_url_for_key(prefixed_key(prefix, job_id, file_name))


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
    return key, public_url_for_key(key)


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
    """Upload emulator captures. Returns ``{file_name: (key, url)}``.

    Legacy helper (``exploration/{job_id}/...``). Prefer
    :func:`upload_object_bytes` + Phase 8 key builders for new code.
    """
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


# --- Phase 8: arbitrary-key upload with retry / verify / delete --------------


def object_exists(key: str) -> bool:
    if not settings.s3_enabled:
        return False
    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except Exception:
        return False


def delete_object(key: str) -> bool:
    if not settings.s3_enabled or not key:
        return False
    try:
        _client().delete_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except Exception:
        logger.warning("Could not delete S3 object key=%s", key, exc_info=True)
        return False


def upload_object_bytes(
    key: str,
    data: bytes,
    *,
    content_type: str = "image/png",
    retries: int | None = None,
    verify: bool | None = None,
) -> tuple[str, str]:
    """Upload ``data`` to ``key`` with retries. Returns ``(key, public_url)``.

    Does not log credentials or object bodies. Raises the last exception when
    all attempts fail.
    """
    if not settings.s3_enabled:
        raise RuntimeError("S3 is not configured.")
    attempts = max(1, int(retries if retries is not None else settings.s3_upload_retries))
    should_verify = settings.s3_verify_uploads if verify is None else bool(verify)
    backoff = max(0.0, float(settings.s3_upload_retry_backoff_seconds or 0.0))
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _client().put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            if should_verify and not object_exists(key):
                raise RuntimeError(f"S3 upload verification failed for key={key}")
            logger.info("S3 upload ok key=%s bytes=%s attempt=%s", key, len(data), attempt)
            return key, public_url_for_key(key)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "S3 upload failed key=%s attempt=%s/%s err=%s",
                key,
                attempt,
                attempts,
                type(exc).__name__,
            )
            if attempt < attempts and backoff:
                time.sleep(backoff * attempt)
    assert last_exc is not None
    raise last_exc
