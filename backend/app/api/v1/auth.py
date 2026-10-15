from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import get_current_user, require_database
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    password_hash_matches,
    verify_password,
)
from app.db.user_repository import (
    EmailAlreadyRegistered,
    create_user,
    get_credentials_by_email,
    get_credentials_by_id,
    set_password_hash,
)
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    UserProfile,
)
from app.services.mailer import send_password_reset_email

logger = logging.getLogger(__name__)
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


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest, background_tasks: BackgroundTasks
) -> MessageResponse:
    require_database()
    found = get_credentials_by_email(str(payload.email))
    if found is None:
        logger.info("Password reset requested for unknown email")
    else:
        user, password_hash = found
        token = create_password_reset_token(user.id, password_hash)
        reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
        # Sent in the background so response time doesn't reveal account existence.
        background_tasks.add_task(
            send_password_reset_email, user.email, user.full_name, reset_url
        )
    # Same response either way so account existence is not revealed.
    return MessageResponse(
        message="If an account exists for that email, reset instructions have been sent."
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest) -> MessageResponse:
    require_database()
    invalid = AppError(
        "INVALID_RESET_TOKEN",
        "This reset link is invalid or has expired. Please request a new one.",
        http_status=400,
    )
    decoded = decode_password_reset_token(payload.token)
    if decoded is None:
        raise invalid
    user_id, fingerprint = decoded
    found = get_credentials_by_id(user_id)
    if found is None or not password_hash_matches(found[1], fingerprint):
        raise invalid
    set_password_hash(user_id, hash_password(payload.password))
    return MessageResponse(message="Your password has been reset. You can now sign in.")


@router.get("/me", response_model=UserProfile)
def current_user(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    return user
