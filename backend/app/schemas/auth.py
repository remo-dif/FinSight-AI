from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class PasswordRequest(BaseModel):
    @field_validator("password", mode="before", check_fields=False)
    @classmethod
    def validate_password_bytes(cls, value: Any) -> Any:
        if isinstance(value, (str, bytes, bytearray)):
            encoded = value.encode("utf-8") if isinstance(value, str) else value
            if len(encoded) > 72:
                raise ValueError("Password must be at most 72 UTF-8 bytes; it is never truncated")
        return value


class RegisterRequest(PasswordRequest):
    email: EmailStr
    password: str = Field(
        min_length=10,
        max_length=72,
        description=(
            "At least 10 characters and at most 72 UTF-8 bytes. "
            "Passwords are never truncated or normalized."
        ),
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    full_name: str = Field(min_length=2, max_length=160)


class LoginRequest(PasswordRequest):
    email: EmailStr
    password: str = Field(
        max_length=72,
        description=(
            "At most 72 UTF-8 bytes; never truncated or normalized. "
            "No minimum length is imposed at login, preserving existing passwords."
        ),
        json_schema_extra={"format": "password", "writeOnly": True},
    )


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: str


class RegistrationResponse(BaseModel):
    message: str = "Registration request processed. Sign in with your credentials; existing accounts keep their current password."
