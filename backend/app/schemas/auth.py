from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    company_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    # bcrypt only reads the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72)

    @field_validator("full_name", "company_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2048)
    password: str = Field(min_length=8, max_length=72)


class MessageResponse(BaseModel):
    message: str


class UserProfile(BaseModel):
    id: str
    full_name: str
    company_name: str
    email: str
    created_at: datetime | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile
