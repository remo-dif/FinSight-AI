from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException

from app.core import security
from app.models.user import RefreshTokenFamily, User

LEGACY_REFRESH_SECRET = "legacy-refresh-secret-12345678901234567890"
LEGACY_ACCESS_SECRET = "legacy-access-secret-12345678901234567890"
LEGACY_REFRESH_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMTExMTExMS0xMTExLTQxMTEtODExMS0xMTExMTExMTExMTEiLCJ0eXBlIjoi"
    "cmVmcmVzaCIsImp0aSI6ImxlZ2FjeS1qdGkiLCJpYXQiOjE1Nzc4MzY4MDAsImV4cCI6NDEw"
    "MjQ0NDgwMH0.cBTyeV6tGXTQBoW7hUFEMA0CLNdgVcZMrdBJXY2ox08"
)
LEGACY_ACCESS_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMTExMTExMS0xMTExLTQxMTEtODExMS0xMTExMTExMTExMTEiLCJ0eXBlIjoi"
    "YWNjZXNzIiwic2lkIjoiMjIyMjIyMjItMjIyMi00MjIyLTgyMjItMjIyMjIyMjIyMjIyIiwiaWF0"
    "IjoxNTc3ODM2ODAwLCJleHAiOjQxMDI0NDQ4MDB9."
    "XaCE-Y2KDviD8NyLCnryr-YQxWgRnOoKPJjcJdT2TR4"
)


def test_refresh_tokens_issued_by_python_jose_remain_valid(monkeypatch):
    monkeypatch.setattr(security.settings, "jwt_refresh_secret_key", LEGACY_REFRESH_SECRET)

    payload = security.decode_refresh_token(LEGACY_REFRESH_TOKEN)

    assert UUID(payload["sub"]) == UUID("11111111-1111-4111-8111-111111111111")
    assert payload["type"] == "refresh"
    assert payload["jti"] == "legacy-jti"


def test_family_bound_access_tokens_issued_by_python_jose_remain_valid(monkeypatch):
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    family_id = UUID("22222222-2222-4222-8222-222222222222")
    user = SimpleNamespace(id=user_id, is_active=True)
    family = SimpleNamespace(id=family_id, user_id=user_id, revoked_at=None)

    class FakeDatabase:
        @staticmethod
        def get(model, item_id):
            if model is RefreshTokenFamily and item_id == family_id:
                return family
            if model is User and item_id == user_id:
                return user
            return None

    monkeypatch.setattr(security.settings, "jwt_secret_key", LEGACY_ACCESS_SECRET)

    assert security.get_current_user(LEGACY_ACCESS_TOKEN, FakeDatabase(), str(family_id)) is user


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        LEGACY_REFRESH_TOKEN[:-1] + "x",
    ],
)
def test_invalid_legacy_refresh_tokens_keep_the_public_401_contract(monkeypatch, token):
    monkeypatch.setattr(security.settings, "jwt_refresh_secret_key", LEGACY_REFRESH_SECRET)

    with pytest.raises(HTTPException) as caught:
        security.decode_refresh_token(token)

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid refresh token"
    assert caught.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize(
    "payload,algorithm",
    [
        (
            {
                "sub": "11111111-1111-4111-8111-111111111111",
                "type": "refresh",
                "jti": "expired",
                "exp": 1,
            },
            "HS256",
        ),
        (
            {
                "sub": "11111111-1111-4111-8111-111111111111",
                "type": "refresh",
                "jti": "wrong-algorithm",
                "exp": 4102444800,
            },
            "HS384",
        ),
        (
            {
                "sub": "11111111-1111-4111-8111-111111111111",
                "type": "refresh",
                "jti": "future-issued-at",
                "iat": 4102444700,
                "exp": 4102444800,
            },
            "HS256",
        ),
    ],
)
def test_expired_or_disallowed_algorithm_refresh_tokens_are_rejected(
    monkeypatch, payload, algorithm
):
    monkeypatch.setattr(security.settings, "jwt_refresh_secret_key", LEGACY_REFRESH_SECRET)
    signing_secret = LEGACY_REFRESH_SECRET if algorithm == "HS256" else "x" * 48
    token = jwt.encode(payload, signing_secret, algorithm=algorithm)

    with pytest.raises(HTTPException) as caught:
        security.decode_refresh_token(token)

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid refresh token"


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": "not-a-uuid", "type": "refresh", "jti": "invalid-sub"},
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "type": "access",
            "jti": "wrong-type",
        },
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "type": "refresh",
        },
    ],
)
def test_invalid_refresh_claims_keep_the_public_401_contract(monkeypatch, payload):
    monkeypatch.setattr(security.settings, "jwt_refresh_secret_key", LEGACY_REFRESH_SECRET)
    token = jwt.encode({**payload, "exp": 4102444800}, LEGACY_REFRESH_SECRET, algorithm="HS256")

    with pytest.raises(HTTPException) as caught:
        security.decode_refresh_token(token)

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid refresh token"


def test_invalid_access_session_identifier_keeps_the_public_401_contract(monkeypatch):
    monkeypatch.setattr(security.settings, "jwt_secret_key", LEGACY_ACCESS_SECRET)
    token = jwt.encode(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "type": "access",
            "sid": "not-a-uuid",
            "exp": 4102444800,
        },
        LEGACY_ACCESS_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as caught:
        security.get_current_user(token, object())

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid authentication credentials"
