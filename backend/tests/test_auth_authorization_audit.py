from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

import app.models  # noqa: F401
from app.api.routes.auth import set_refresh_cookie
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import TokenType, create_token, hash_password
from app.main import create_app
from app.models.audit import AuditLog
from app.models.case import CaseNote, InvestigationCase
from app.models.finance import Transaction
from app.models.user import RefreshToken, User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def make_user(db, email: str, *, active: bool = True) -> User:
    user = User(
        email=email,
        full_name=email.partition("@")[0],
        password_hash=hash_password("synthetic audit password"),
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def api(db):
    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return app


def test_refresh_cookie_lifetime_matches_configured_refresh_token_lifetime(monkeypatch):
    monkeypatch.setattr(settings, "refresh_token_days", 11)
    response = Response()

    set_refresh_cookie(response, "synthetic-refresh-token")

    cookie = next(
        value
        for value in response.headers.getlist("set-cookie")
        if value.startswith("finsight_refresh_token=")
    )
    assert "Max-Age=950400" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/auth" in cookie


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_malformed_expired_and_wrong_signature_tokens(api, db):
    user = make_user(db, "jwt-audit@example.test")
    expired = create_token(user.id, TokenType.ACCESS, timedelta(seconds=-1))
    incorrectly_signed = jwt.encode(
        {
            "sub": str(user.id),
            "type": TokenType.ACCESS.value,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=1)).timestamp()),
        },
        "incorrect-synthetic-signing-secret",
        algorithm=settings.jwt_algorithm,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        responses = [
            await client.get("/api/auth/me"),
            await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}),
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}),
            await client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {incorrectly_signed}"}
            ),
        ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]


@pytest.mark.asyncio
async def test_access_and_refresh_tokens_are_rejected_in_the_opposite_context(api, db):
    user = make_user(db, "token-swap@example.test")
    access_token = create_token(user.id, TokenType.ACCESS)
    refresh_token = create_token(user.id, TokenType.REFRESH, jti="synthetic-unpersisted-jti")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        refresh_as_access = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
        )
        access_as_refresh = await client.post(
            "/api/auth/refresh", json={"refresh_token": access_token}
        )

    assert refresh_as_access.status_code == 401
    assert access_as_refresh.status_code == 401
    assert db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id)) is None


@pytest.mark.asyncio
async def test_deactivated_user_access_token_is_rejected(api, db):
    user = make_user(db, "inactive-audit@example.test", active=False)
    token = create_token(user.id, TokenType.ACCESS)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_cannot_access_or_mutate_another_users_case_notes_or_transactions(api, db):
    owner = make_user(db, "owner-audit@example.test")
    other = make_user(db, "other-audit@example.test")
    foreign_transaction = Transaction(
        user_id=owner.id,
        posted_at=date(2026, 10, 1),
        merchant="Synthetic evidence merchant",
        description="Synthetic audit fixture",
        amount=Decimal("-31.25"),
        currency="EUR",
        category="Synthetic",
        source="manual",
    )
    db.add(foreign_transaction)
    db.flush()
    foreign_case = InvestigationCase(transaction_id=foreign_transaction.id)
    foreign_note = CaseNote(
        case_id=foreign_transaction.id, author_id=owner.id, content="Private synthetic note"
    )
    owned_transaction = Transaction(
        user_id=other.id,
        posted_at=date(2026, 10, 2),
        merchant="User B synthetic merchant",
        description="User B's synthetic audit fixture",
        amount=Decimal("-12.00"),
        currency="EUR",
        category="Synthetic",
        source="manual",
    )
    db.add(owned_transaction)
    db.flush()
    owned_case = InvestigationCase(transaction_id=owned_transaction.id)
    owned_note = CaseNote(
        case_id=owned_transaction.id, author_id=other.id, content="User B private synthetic note"
    )
    db.add_all([foreign_case, foreign_note, owned_case, owned_note])
    db.commit()

    api.dependency_overrides.clear()
    api.dependency_overrides[get_db] = lambda: db
    from app.core.security import get_current_user

    api.dependency_overrides[get_current_user] = lambda: other
    before_case = (foreign_case.status, foreign_case.assignee_user_id, foreign_case.decision)
    before_note_count = db.query(CaseNote).filter(CaseNote.case_id == foreign_transaction.id).count()
    before_audit_count = db.query(AuditLog).count()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test"
    ) as client:
        list_response = await client.get("/api/cases")
        detail_response = await client.get(f"/api/cases/{foreign_transaction.id}")
        update_response = await client.patch(
            f"/api/cases/{foreign_transaction.id}", json={"status": "escalated"}
        )
        note_response = await client.post(
            f"/api/cases/{foreign_transaction.id}/notes", json={"content": "Unauthorized change"}
        )
        transaction_response = await client.get("/api/transactions")
        own_detail = await client.get(f"/api/cases/{owned_transaction.id}")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [str(owned_transaction.id)]
    assert detail_response.status_code == update_response.status_code == note_response.status_code == 404
    assert transaction_response.status_code == 200
    assert [row["id"] for row in transaction_response.json()] == [str(owned_transaction.id)]
    assert all(row["id"] != str(foreign_transaction.id) for row in transaction_response.json())

    assert own_detail.status_code == 200
    assert [note["content"] for note in own_detail.json()["notes"]] == [
        "User B private synthetic note"
    ]

    db.expire_all()
    persisted_case = db.get(InvestigationCase, foreign_transaction.id)
    assert (persisted_case.status, persisted_case.assignee_user_id, persisted_case.decision) == before_case
    assert db.query(CaseNote).filter(CaseNote.case_id == foreign_transaction.id).count() == before_note_count
    assert db.query(AuditLog).count() == before_audit_count

