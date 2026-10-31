"""Public JSON login and bearer contract; validation must not echo credentials."""

import httpx
import pytest

from app.core.database import get_db
from app.main import create_app
from tests import test_auth as auth_fixtures

db = auth_fixtures.db


def test_openapi_describes_bearer_tokens_instead_of_an_unsupported_form_login():
    schema = create_app().openapi()
    assert schema["components"]["securitySchemes"] == {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Obtain an access_token with JSON POST /api/auth/login, then send Authorization: Bearer <access_token>.",
        }
    }
    for path, method in [("/api/auth/me", "get"), ("/api/chat", "post"), ("/api/uploads", "post")]:
        assert schema["paths"][path][method]["security"] == [{"BearerAuth": []}]
    login = schema["paths"]["/api/auth/login"]["post"]
    assert list(login["requestBody"]["content"]) == ["application/json"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/auth/register",
            {
                "email": "user@example.com",
                "full_name": "Synthetic",
                "password": "sensitive-synthetic-password-" * 5,
            },
        ),
        (
            "/api/auth/login",
            {"email": "user@example.com", "password": ["sensitive-synthetic-password-"]},
        ),
        ("/api/auth/login", [{"password": "sensitive-synthetic-password-"}]),
        ("/api/auth/refresh", {"refresh_token": ["sensitive-synthetic-password-"]}),
        ("/api/auth/logout", {"refresh_token": ["sensitive-synthetic-password-"]}),
    ],
)
async def test_auth_validation_retains_actionable_errors_without_echoing_input(db, path, payload):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(path, json=payload)
        assert response.status_code == 422
        assert "sensitive-synthetic-password-" not in response.text
        errors = response.json()["detail"]
        assert errors
        assert all("input" not in error for error in errors)
        assert all({"loc", "msg", "type"} <= error.keys() for error in errors)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "message"),
    [
        (None, "Not authenticated"),
        ("Basic synthetic", "Not authenticated"),
        ("Bearer", "Invalid authentication credentials"),
        ("Bearer not-a-jwt", "Invalid authentication credentials"),
    ],
)
async def test_existing_missing_and_malformed_bearer_responses_remain_unchanged(
    db, authorization, message
):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/auth/me", headers={"Authorization": authorization} if authorization else {}
            )
        assert response.status_code == 401
        assert response.json() == {"detail": message}
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        app.dependency_overrides.clear()
