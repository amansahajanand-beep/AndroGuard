from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# bcrypt only reads the first 72 bytes of a password and silently ignores the rest.
BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(password), hashed_password.encode())
    except ValueError:
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


def _encode(password: str) -> bytes:
    return password.encode()[:BCRYPT_MAX_PASSWORD_BYTES]
