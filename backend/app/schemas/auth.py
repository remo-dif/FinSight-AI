from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class PasswordRequest(BaseModel):
    @field_validator("password", check_fields=False)
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes; it is never truncated")
        return value


class RegisterRequest(PasswordRequest):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)


class LoginRequest(PasswordRequest):
    email: EmailStr
    password: str


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
