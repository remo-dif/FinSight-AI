"""Password limits describe the existing UTF-8 policy without changing hashing."""

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.main import create_app
from app.models.user import RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest
from tests import test_auth as auth_fixtures

db = auth_fixtures.db


@pytest.mark.parametrize("name", ["RegisterRequest", "LoginRequest"])
def test_openapi_password_limits_describe_utf8_bytes_and_secret_fields(name):
    schema = create_app().openapi()["components"]["schemas"][name]["properties"]["password"]
    assert schema["maxLength"] == 72
    assert "72 UTF-8 bytes" in schema["description"]
    assert "truncated" in schema["description"]
    assert schema["format"] == "password"
    assert schema["writeOnly"] is True
    if name == "RegisterRequest":
        assert schema["minLength"] == 10
        assert "10 characters" in schema["description"]
    else:
        assert "minLength" not in schema


@pytest.mark.parametrize("request_type", [RegisterRequest, LoginRequest])
@pytest.mark.parametrize(
    ("password", "valid"),
    [
        ("A" * 72, True),
        ("A" * 73, False),
        ("è" * 36, True),
        ("è" * 36 + "a", False),
        ("😀" * 18, True),
        ("😀" * 18 + "a", False),
        ("e\u0301" * 24, True),
        ("e\u0301" * 24 + "a", False),
    ],
)
def test_both_auth_requests_enforce_exact_72_byte_boundary(request_type, password, valid):
    data = {"email": "synthetic@example.com", "password": password}
    if request_type is RegisterRequest:
        data["full_name"] = "Synthetic Analyst"
    if valid:
        assert request_type(**data).password == password
    else:
        with pytest.raises(ValidationError):
            request_type(**data)


def test_registration_minimum_is_characters_while_login_keeps_legacy_short_passwords():
    with pytest.raises(ValidationError):
        RegisterRequest(email="synthetic@example.com", password="è" * 9, full_name="Synthetic")
    assert (
        RegisterRequest(
            email="synthetic@example.com", password="è" * 10, full_name="Synthetic"
        ).password
        == "è" * 10
    )
    assert LoginRequest(email="synthetic@example.com", password="legacy").password == "legacy"


@pytest.mark.parametrize("request_type", [RegisterRequest, LoginRequest])
@pytest.mark.parametrize("container", [bytes, bytearray])
def test_programmatic_utf8_input_coercion_cannot_bypass_the_byte_limit(request_type, container):
    data = {"email": "synthetic@example.com", "full_name": "Synthetic"}
    assert request_type(**data, password=container(("è" * 36).encode("utf-8"))).password == "è" * 36
    with pytest.raises(ValidationError):
        request_type(**data, password=container(("è" * 37).encode("utf-8")))


@pytest.mark.parametrize("password", ["A" * 72, "è" * 36, "😀" * 18, "e\u0301" * 24])
def test_hashing_preserves_exact_password_without_unicode_or_whitespace_normalization(password):
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password(password[:-1], hashed)
    assert not verify_password(password + "a", hashed)


def test_composed_and_decomposed_passwords_are_not_silently_normalized():
    composed = "é" * 12
    decomposed = "e\u0301" * 12
    hashed = hash_password(composed)
    assert verify_password(composed, hashed)
    assert not verify_password(decomposed, hashed)
    spaced = "  synthetic password  "
    assert verify_password(spaced, hash_password(spaced))
    assert not verify_password(spaced.strip(), hash_password(spaced))


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["A" * 72, "è" * 36, "😀" * 18])
async def test_http_register_and_login_accept_72_bytes_and_never_modify_the_hash(db, password):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            data = {
                "email": "synthetic@example.com",
                "password": password,
                "full_name": "Synthetic",
            }
            registered = await client.post("/api/auth/register", json=data)
            assert registered.status_code == 201
            user = db.scalar(select(User).where(User.email == data["email"]))
            stored_hash = user.password_hash
            logged_in = await client.post(
                "/api/auth/login", json={"email": data["email"], "password": password}
            )
            assert logged_in.status_code == 200
            assert logged_in.json()["token_type"] == "bearer"
            db.refresh(user)
            assert user.password_hash == stored_hash
            assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["A" * 73, "è" * 36 + "a", "😀" * 18 + "a"])
async def test_http_oversize_validation_is_422_without_users_or_tokens(db, password):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("/api/auth/register", "/api/auth/login"):
                response = await client.post(
                    path,
                    json={
                        "email": "synthetic@example.com",
                        "password": password,
                        "full_name": "Synthetic",
                    },
                )
                assert response.status_code == 422
                assert not response.headers.get_list("set-cookie")
            assert db.scalar(select(func.count()).select_from(User)) == 0
            assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0
    finally:
        app.dependency_overrides.clear()
