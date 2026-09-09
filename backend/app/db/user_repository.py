from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import User
from app.db.session import SessionLocal, engine
from app.schemas.auth import UserProfile

logger = logging.getLogger(__name__)


class EmailAlreadyRegistered(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _to_profile(row: User) -> UserProfile:
    return UserProfile(
        id=row.id,
        full_name=row.full_name,
        company_name=row.company_name,
        email=row.email,
        created_at=row.created_at,
    )


def create_user(full_name: str, company_name: str, email: str, password_hash: str) -> UserProfile:
    if engine is None or SessionLocal is None:
        raise RuntimeError("Database is not configured.")
    session = SessionLocal()
    try:
        row = User(
            id=str(uuid.uuid4()),
            full_name=full_name,
            company_name=company_name,
            email=normalize_email(email),
            password_hash=password_hash,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_profile(row)
    except IntegrityError as exc:
        session.rollback()
        raise EmailAlreadyRegistered(email) from exc
    except Exception:
        session.rollback()
        logger.exception("Failed to create user")
        raise
    finally:
        session.close()


def get_credentials_by_email(email: str) -> tuple[UserProfile, str] | None:
    if engine is None or SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        stmt = select(User).where(User.email == normalize_email(email))
        row = session.scalars(stmt).first()
        if row is None:
            return None
        return _to_profile(row), row.password_hash
    finally:
        session.close()


def get_user_by_id(user_id: str) -> UserProfile | None:
    if engine is None or SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        row = session.get(User, user_id)
        return None if row is None else _to_profile(row)
    finally:
        session.close()
