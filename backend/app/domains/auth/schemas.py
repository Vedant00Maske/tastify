"""API representations for authentication and the current user (API_SPEC.md)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domains.auth.passwords import MAX_LENGTH

# Deliberately simple: one "@", a dot in the domain, no spaces. Deliverability is not checked.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(value: str) -> str:
    cleaned = value.strip().lower()
    if len(cleaned) > 254 or not _EMAIL.match(cleaned):
        raise ValueError("enter a valid e-mail address")
    return cleaned


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_LENGTH)
    display_name: str | None = Field(default=None, max_length=80)
    accept_terms: bool = Field(description="Terms and privacy acknowledgement; must be true.")

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=MAX_LENGTH)
    new_password: str = Field(max_length=MAX_LENGTH)


class PasswordResetRequestIn(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        return _email(value)


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    new_password: str = Field(max_length=MAX_LENGTH)


class EmailVerifyIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class AccountDeleteIn(BaseModel):
    password: str = Field(max_length=MAX_LENGTH)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    onboarding_completed: bool
    email_verified: bool


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    onboarding_completed: bool | None = None
