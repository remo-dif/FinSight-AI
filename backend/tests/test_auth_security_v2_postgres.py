"""Refresh-family serialization, enrollment races and populated migration on PostgreSQL."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.routes import auth
from app.models.audit import AuditLog
from app.models.user import RefreshToken, RefreshTokenFamily
from app.schemas.auth import RefreshTokenRequest, RegisterRequest
from tests import test_case_workflow_postgres as pg_fixtures
from tests.test_auth_security_v2 import rotate, sign_in

case_pg = pg_fixtures.case_pg


@pytest.mark.parametrize("operation", ["refresh", "logout"])
def test_concurrent_family_operations_never_leave_a_valid_successor_after_replay_or_logout(
    case_pg, monkeypatch, operation
):
    engine, _ = case_pg
    # The case fixture owns an isolated schema; enrollment uses a separate test identity.
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        independent = sign_in(db)
        family_id = db.scalar(
            select(RefreshToken.family_id).where(
                RefreshToken.jti == auth.decode_refresh_token(first.refresh_token)["jti"]
            )
        )
    barrier = Barrier(2, timeout=10)
    original = Session.scalar

    def same_snapshot(self, statement, *args, **kwargs):
        result = original(self, statement, *args, **kwargs)
        descriptions = getattr(statement, "column_descriptions", [])
        if descriptions and descriptions[0].get("entity") is RefreshToken:
            barrier.wait()
        return result

    def apply(action):
        with Session(engine, autoflush=False) as db:
            try:
                # The refresh/refresh case models two tabs with separate in-memory single-flight state.
                if action == "logout":
                    auth.logout(
                        RefreshTokenRequest(refresh_token=first.refresh_token), Response(), db
                    )
                    return 204
                rotate(db, first.refresh_token)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with monkeypatch.context() as patch:
        patch.setattr(Session, "scalar", same_snapshot)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, ["refresh", operation]))
    if operation == "refresh":
        assert sorted(results) == [200, 401]
    else:
        assert 204 in results and results[0] in {200, 401}
    with Session(engine) as db:
        tokens = list(db.scalars(select(RefreshToken).where(RefreshToken.family_id == family_id)))
        assert len(tokens) <= 2
        assert all(token.revoked_at is not None for token in tokens)
        assert db.get(RefreshTokenFamily, family_id).revoked_at is not None
        assert rotate(db, independent.refresh_token).refresh_token
        events = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action
                    == ("auth.refresh_reuse" if operation == "refresh" else "auth.logout")
                )
            )
        )
        assert len(events) == 1


def test_concurrent_registration_has_one_account_and_identical_responses(case_pg, monkeypatch):
    engine, _ = case_pg
    barrier = Barrier(2, timeout=10)
    original = Session.scalar

    def same_snapshot(self, statement, *args, **kwargs):
        result = original(self, statement, *args, **kwargs)
        if "WHERE users.email" in str(statement) and "users.password_hash" in str(statement):
            barrier.wait()
        return result

    def apply(index):
        with Session(engine, autoflush=False) as db:
            return auth.register(
                RegisterRequest(
                    email="race@example.com",
                    password="synthetic-password",
                    full_name=f"Contender {index}",
                ),
                db,
            ).model_dump()

    with monkeypatch.context() as patch:
        patch.setattr(Session, "scalar", same_snapshot)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(apply, [1, 2]))
    assert replies[0] == replies[1] and set(replies[0]) == {"message"}
    from app.models.user import User

    with Session(engine) as db:
        users = list(db.scalars(select(User).where(User.email == "race@example.com")))
        assert len(users) == 1
        assert (
            len(list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.register")))) == 1
        )


def migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261031_0007_refresh_token_families.py"
    )
    spec = importlib.util.spec_from_file_location("family_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _remove_refresh_families(engine):
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE refresh_tokens DROP COLUMN family_id"))
        connection.execute(text("DROP TABLE refresh_token_families"))


def _upgrade_refresh_families(engine):
    migration = migration_module()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()


def _assert_refresh_family_migration_rolled_back(engine, before):
    with engine.connect() as connection:
        after = list(
            connection.execute(
                text(
                    "SELECT id, jti, token_hash, expires_at, revoked_at, replaced_by_jti "
                    "FROM refresh_tokens ORDER BY id"
                )
            )
        )
        assert after == before
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'refresh_token_families'"
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'refresh_tokens' AND column_name = 'family_id'"
                )
            )
            == 0
        )


def test_migration_rejects_reachable_cycle_without_partial_changes(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        second = rotate(db, first.refresh_token)
        third = rotate(db, second.refresh_token)
        first_jti = auth.decode_refresh_token(first.refresh_token)["jti"]
        second_jti = auth.decode_refresh_token(second.refresh_token)["jti"]
        third_jti = auth.decode_refresh_token(third.refresh_token)["jti"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE refresh_tokens SET replaced_by_jti = :second WHERE jti = :third"),
            {"second": second_jti, "third": third_jti},
        )
        before = list(
            connection.execute(
                text(
                    "SELECT id, jti, token_hash, expires_at, revoked_at, replaced_by_jti "
                    "FROM refresh_tokens ORDER BY id"
                )
            )
        )
    _remove_refresh_families(engine)

    with pytest.raises(RuntimeError, match="inconsistent") as exc:
        _upgrade_refresh_families(engine)

    assert "cycle among token rows" in str(exc.value)
    assert first.refresh_token not in str(exc.value)
    _assert_refresh_family_migration_rolled_back(engine, before)
    assert {row[1] for row in before} == {first_jti, second_jti, third_jti}


def test_migration_rejects_active_token_with_successor_without_partial_changes(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        second = sign_in(db)
        first_jti = auth.decode_refresh_token(first.refresh_token)["jti"]
        second_jti = auth.decode_refresh_token(second.refresh_token)["jti"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE refresh_tokens SET replaced_by_jti = :second WHERE jti = :first"),
            {"first": first_jti, "second": second_jti},
        )
        before = list(
            connection.execute(
                text(
                    "SELECT id, jti, token_hash, expires_at, revoked_at, replaced_by_jti "
                    "FROM refresh_tokens ORDER BY id"
                )
            )
        )
    _remove_refresh_families(engine)

    with pytest.raises(RuntimeError, match="inconsistent") as exc:
        _upgrade_refresh_families(engine)

    assert "active token row" in str(exc.value)
    assert first.refresh_token not in str(exc.value)
    _assert_refresh_family_migration_rolled_back(engine, before)


def test_migration_assigns_single_token_to_its_own_family(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        login = sign_in(db)
        jti = auth.decode_refresh_token(login.refresh_token)["jti"]
        token = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
        token_id = token.id
    _remove_refresh_families(engine)

    _upgrade_refresh_families(engine)

    with Session(engine) as db:
        token = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
        family = db.get(RefreshTokenFamily, token_id)
        assert token.family_id == token_id
        assert family is not None
        assert family.user_id == token.user_id
        assert family.revoked_at is None
        assert rotate(db, login.refresh_token).refresh_token


def test_migration_accepts_expired_unrevoked_terminal_token(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        login = sign_in(db)
        jti = auth.decode_refresh_token(login.refresh_token)["jti"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE refresh_tokens SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second' "
                "WHERE jti = :jti"
            ),
            {"jti": jti},
        )
    _remove_refresh_families(engine)

    _upgrade_refresh_families(engine)

    with Session(engine) as db:
        token = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
        family = db.get(RefreshTokenFamily, token.family_id)
        assert token.revoked_at is None
        assert token.expires_at < auth.utc_now()
        assert family.revoked_at is None
        with pytest.raises(HTTPException):
            rotate(db, login.refresh_token)


def test_migration_rejects_successor_with_multiple_revoked_predecessors(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        second = sign_in(db)
        successor = sign_in(db)
        first_jti = auth.decode_refresh_token(first.refresh_token)["jti"]
        second_jti = auth.decode_refresh_token(second.refresh_token)["jti"]
        successor_jti = auth.decode_refresh_token(successor.refresh_token)["jti"]
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE refresh_tokens
                SET replaced_by_jti = :successor, revoked_at = CURRENT_TIMESTAMP
                WHERE jti IN (:first, :second)
            """),
            {"first": first_jti, "second": second_jti, "successor": successor_jti},
        )
        before = list(
            connection.execute(
                text(
                    "SELECT id, jti, token_hash, expires_at, revoked_at, replaced_by_jti "
                    "FROM refresh_tokens ORDER BY id"
                )
            )
        )
    _remove_refresh_families(engine)

    with pytest.raises(RuntimeError, match="multiple predecessors"):
        _upgrade_refresh_families(engine)

    _assert_refresh_family_migration_rolled_back(engine, before)


@pytest.mark.parametrize(
    ("relationship", "expected_error"),
    [("dangling", "missing successor"), ("cross_user", "crosses users")],
)
def test_migration_rejects_invalid_successor_relationships(case_pg, relationship, expected_error):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        auth.register(
            RegisterRequest(
                email="other@example.com",
                password="correct horse battery staple",
                full_name="Other User",
            ),
            db,
        )
        parent = sign_in(db)
        parent_jti = auth.decode_refresh_token(parent.refresh_token)["jti"]
        successor_jti = (
            auth.decode_refresh_token(sign_in(db, "other@example.com").refresh_token)["jti"]
            if relationship == "cross_user"
            else "missing-successor-jti"
        )
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE refresh_tokens
                SET replaced_by_jti = :successor, revoked_at = CURRENT_TIMESTAMP
                WHERE jti = :parent
            """),
            {"parent": parent_jti, "successor": successor_jti},
        )
        before = list(
            connection.execute(
                text(
                    "SELECT id, jti, token_hash, expires_at, revoked_at, replaced_by_jti "
                    "FROM refresh_tokens ORDER BY id"
                )
            )
        )
    _remove_refresh_families(engine)

    with pytest.raises(RuntimeError, match=expected_error):
        _upgrade_refresh_families(engine)

    _assert_refresh_family_migration_rolled_back(engine, before)


def test_populated_migration_preserves_legacy_tokens_chains_and_independent_sessions(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        root = sign_in(db)
        child = rotate(db, root.refresh_token)
        independent = sign_in(db)
        logged_out = sign_in(db)
        auth.logout(RefreshTokenRequest(refresh_token=logged_out.refresh_token), Response(), db)
        before = [
            (token.jti, token.token_hash, token.replaced_by_jti)
            for token in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
        ]
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE refresh_tokens DROP COLUMN family_id"))
        connection.execute(text("DROP TABLE refresh_token_families"))
    migration = migration_module()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    with Session(engine) as db:
        after = [
            (token.jti, token.token_hash, token.replaced_by_jti)
            for token in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
        ]
        assert before == after
        assert len(list(db.scalars(select(RefreshTokenFamily)))) == 3
        family_ids = {token.jti: token.family_id for token in db.scalars(select(RefreshToken))}
        root_jti = auth.decode_refresh_token(root.refresh_token)["jti"]
        child_jti = auth.decode_refresh_token(child.refresh_token)["jti"]
        independent_jti = auth.decode_refresh_token(independent.refresh_token)["jti"]
        logged_out_jti = auth.decode_refresh_token(logged_out.refresh_token)["jti"]
        assert family_ids[root_jti] == family_ids[child_jti]
        assert family_ids[root_jti] != family_ids[independent_jti]
        assert family_ids[independent_jti] != family_ids[logged_out_jti]
        assert db.get(RefreshTokenFamily, family_ids[logged_out_jti]).revoked_at is not None
        assert rotate(db, child.refresh_token).refresh_token
        with pytest.raises(HTTPException):
            rotate(db, root.refresh_token)
        assert rotate(db, independent.refresh_token).refresh_token
        with pytest.raises(HTTPException):
            rotate(db, logged_out.refresh_token)


def test_migration_aborts_cycle_without_partial_schema_or_token_changes(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        second = sign_in(db)
        first_jti = auth.decode_refresh_token(first.refresh_token)["jti"]
        second_jti = auth.decode_refresh_token(second.refresh_token)["jti"]
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE refresh_tokens DROP COLUMN family_id"))
        connection.execute(text("DROP TABLE refresh_token_families"))
        connection.execute(
            text(
                "UPDATE refresh_tokens SET replaced_by_jti = CASE WHEN jti = :first THEN :second ELSE :first END"
            ),
            {"first": first_jti, "second": second_jti},
        )
    migration = migration_module()
    with pytest.raises(RuntimeError, match="inconsistent"), engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM refresh_tokens")) == 2
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'refresh_token_families'"
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'refresh_tokens' AND column_name = 'family_id'"
                )
            )
            == 0
        )


@pytest.mark.parametrize("operation", ["rotation", "replay", "logout"])
def test_postgres_audit_failure_rolls_back_family_state_and_token_creation(
    case_pg, monkeypatch, operation
):
    from sqlalchemy.exc import IntegrityError

    engine, _ = case_pg
    with Session(engine) as db:
        auth.register(
            RegisterRequest(
                email="user@example.com",
                password="correct horse battery staple",
                full_name="Security User",
            ),
            db,
        )
        first = sign_in(db)
        if operation != "rotation":
            rotate(db, first.refresh_token)
        family_id = db.scalar(
            select(RefreshToken.family_id).where(
                RefreshToken.jti == auth.decode_refresh_token(first.refresh_token)["jti"]
            )
        )
        before = [
            (row.jti, row.revoked_at, row.replaced_by_jti)
            for row in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
        ]

    def invalid_audit(self, *args, **kwargs):
        self.db.add(AuditLog(action=None))

    with monkeypatch.context() as patch:
        patch.setattr(auth.AuditService, "record", invalid_audit)
        with Session(engine, autoflush=False) as db, pytest.raises(IntegrityError):
            if operation == "logout":
                auth.logout(RefreshTokenRequest(refresh_token=first.refresh_token), Response(), db)
            else:
                rotate(db, first.refresh_token)
    with Session(engine) as db:
        after = [
            (row.jti, row.revoked_at, row.replaced_by_jti)
            for row in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
        ]
        assert before == after
        assert db.get(RefreshTokenFamily, family_id).revoked_at is None
