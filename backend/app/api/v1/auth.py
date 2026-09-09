from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, require_database
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.user_repository import (
    EmailAlreadyRegistered,
    create_user,
    get_credentials_by_email,
)
from app.schemas.auth import AuthResponse, LoginRequest, SignupRequest, UserProfile

router = APIRouter(prefix="/auth")


def _auth_response(user: UserProfile) -> AuthResponse:
    token, expires_in = create_access_token(user.id)
    return AuthResponse(access_token=token, expires_in=expires_in, user=user)


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(payload: SignupRequest) -> AuthResponse:
    require_database()
    try:
        user = create_user(
            full_name=payload.full_name,
            company_name=payload.company_name,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
        )
    except EmailAlreadyRegistered as exc:
        raise AppError(
            "EMAIL_ALREADY_REGISTERED",
            "An account with this email address already exists.",
            http_status=409,
        ) from exc
    return _auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    require_database()
    found = get_credentials_by_email(str(payload.email))
    if found is None or not verify_password(payload.password, found[1]):
        raise AppError(
            "INVALID_CREDENTIALS",
            "Email address or password is incorrect.",
            http_status=401,
        )
    return _auth_response(found[0])


@router.get("/me", response_model=UserProfile)
def current_user(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    return user
