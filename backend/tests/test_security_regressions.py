from io import BytesIO
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile, status
from jose import jwt
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import TokenType, create_token, get_current_user, settings
from app.services.ingestion import SecureUploadService


def production_settings(**overrides):
    defaults = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://finance:finance@localhost:5432/finance_ai",
        "jwt_secret_key": "access-secret-for-production-tests-123",
        "jwt_refresh_secret_key": "refresh-secret-for-production-tests-123",
        "allowed_origins": ["https://finance.example.com"],
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_production_rejects_sqlite_database_url():
    with pytest.raises(ValidationError, match="DATABASE_URL must not use SQLite"):
        production_settings(database_url="sqlite+pysqlite:///./finance_ai.db")


def test_production_rejects_wildcard_cors_origin():
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS must be explicit"):
        production_settings(allowed_origins=["*"])


def test_production_rejects_unsafe_or_short_jwt_secrets():
    with pytest.raises(ValidationError, match="JWT secrets must be set to strong"):
        production_settings(jwt_secret_key="dev-secret")

    with pytest.raises(ValidationError, match="JWT secrets must be at least 32"):
        production_settings(jwt_secret_key="short-secret")


def test_refresh_token_is_not_accepted_as_access_token():
    token = create_token(uuid4(), TokenType.REFRESH)

    with pytest.raises(HTTPException) as exc:
        get_current_user(token=token, db=SimpleNamespace(get=lambda *_: None))

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_token_with_non_access_type_is_rejected_even_when_signed_with_access_secret():
    payload = {"sub": str(uuid4()), "type": TokenType.REFRESH.value}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(HTTPException) as exc:
        get_current_user(token=token, db=SimpleNamespace(get=lambda *_: None))

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_upload_metadata_rejects_extension_and_content_type_mismatches():
    uploader = SecureUploadService()

    with pytest.raises(HTTPException, match="Unsupported file extension"):
        uploader.validate_metadata(SimpleNamespace(filename="statement.exe", content_type="text/csv"))

    with pytest.raises(HTTPException, match="Unsupported content type"):
        uploader.validate_metadata(SimpleNamespace(filename="statement.csv", content_type="text/plain"))


def test_upload_payload_rejects_spoofed_binary_signatures():
    uploader = SecureUploadService()

    with pytest.raises(HTTPException, match="File content does not match extension"):
        uploader.validate_payload(b"not actually a pdf", ".pdf")


@pytest.mark.asyncio
async def test_upload_save_uses_generated_filename_under_user_directory(monkeypatch):
    upload_root = Path(__file__).parent / ".upload-test-output" / str(uuid4())
    monkeypatch.setattr(settings, "upload_dir", upload_root)
    file = UploadFile(
        filename="../../statement.csv",
        file=BytesIO(b"date,merchant,amount\n2026-05-30,Coffee,-5.00\n"),
    )
    file.headers = {"content-type": "text/csv"}
    user_id = uuid4()

    try:
        saved_path = await SecureUploadService().save(user_id, file)

        assert saved_path.parent == upload_root / str(user_id)
        assert saved_path.name != "../../statement.csv"
        assert saved_path.suffix == ".csv"
        assert saved_path.read_bytes().startswith(b"date,merchant,amount")
    finally:
        shutil.rmtree(upload_root.parent, ignore_errors=True)
