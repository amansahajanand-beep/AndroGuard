from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> tuple[str, int]:
    expires_in = settings.access_token_expire_minutes * 60
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def _hash_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(user_id: str, password_hash: str) -> str:
    """Signed, short-lived token. Bound to the current password hash, so it stops
    working once the password changes (single use)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "purpose": "password_reset",
        "fp": _hash_fingerprint(password_hash),
        "iat": now,
        "exp": now + timedelta(minutes=settings.password_reset_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_password_reset_token(token: str) -> tuple[str, str] | None:
    """Return (user_id, password-hash fingerprint) for a valid reset token."""
    payload = decode_access_token(token)
    if not payload or payload.get("purpose") != "password_reset":
        return None
    return payload["sub"], payload.get("fp", "")


def password_hash_matches(password_hash: str, fingerprint: str) -> bool:
    return hmac.compare_digest(_hash_fingerprint(password_hash), fingerprint)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
