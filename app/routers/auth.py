from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserResponse
from app.security import create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)
DECOY_PASSWORD_HASH = hash_password("decoy-password-for-constant-time-login")

DbSession = Annotated[Session, Depends(get_db)]


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None or not payload.get("sub"):
        raise unauthorized

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise unauthorized
    return user


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()

    user = User(
        full_name=payload.full_name.strip(),
        company_name=payload.company_name.strip(),
        email=email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    db.refresh(user)

    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # Hash against a decoy when the email is unknown so unregistered emails
    # can't be identified by the faster response.
    password_ok = verify_password(
        payload.password, user.hashed_password if user else DECOY_PASSWORD_HASH
    )

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    return _token_response(user)


@router.get("/me", response_model=UserResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
