from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from openai import OpenAIError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

import app.models  # noqa: F401
from app.api.routes.uploads import upload_file
from app.core.database import Base
from app.core.openai_resilience import CircuitBreaker, CircuitOpenError
from app.models.embedding import Embedding
from app.models.finance import UploadedFile
from app.models.user import User
from app.services.document_ingestion import DocumentIngestionService
from app.services.rag import LOCAL_EMBEDDING_MODEL


def file():
    return UploadFile(
        BytesIO(b"%PDF-1.4 Synthetic"),
        filename="synthetic.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


def configure(monkeypatch, **values):
    from app.core.config import settings

    namespace = SimpleNamespace(
        **{**settings.model_dump(), "embedding_backend": "openai", **values}
    )
    monkeypatch.setattr("app.services.document_ingestion.settings", namespace)
    monkeypatch.setattr("app.services.document_ingestion.openai_circuit", CircuitBreaker(5, 30))


@pytest.mark.asyncio
async def test_remote_failure_never_switches_embedding_model(monkeypatch):
    configure(monkeypatch)
    service = DocumentIngestionService()

    async def fail(**kwargs):
        raise OpenAIError("Synthetic unavailable provider")

    service._openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=fail))
    with pytest.raises(HTTPException) as exc:
        await service.embed_texts(["Synthetic"])
    assert exc.value.status_code == 503 and "retry" in exc.value.detail.lower()
    assert service.embedding_model != LOCAL_EMBEDDING_MODEL


@pytest.mark.asyncio
async def test_explicit_local_backend_does_not_use_remote_provider(monkeypatch):
    configure(monkeypatch, embedding_backend="local")
    service = DocumentIngestionService()
    assert service._openai_client is None
    assert service.embedding_model == LOCAL_EMBEDDING_MODEL
    assert len((await service.embed_texts(["Synthetic"]))[0]) == 1536


@pytest.mark.asyncio
async def test_missing_remote_client_is_not_implicit_local_mode(monkeypatch):
    configure(monkeypatch)
    service = DocumentIngestionService()
    service._openai_client = None
    with pytest.raises(HTTPException) as exc:
        await service.embed_texts(["Synthetic"])
    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [[0.0]], [[float("nan")] * 1536], [[float("inf")] * 1536]])
async def test_invalid_remote_embedding_response_is_not_indexed(monkeypatch, rows):
    configure(monkeypatch)
    service = DocumentIngestionService()

    async def create(**kwargs):
        return SimpleNamespace(
            model=service.embedding_model,
            data=[SimpleNamespace(index=i, embedding=row) for i, row in enumerate(rows)]
        )

    service._openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    with pytest.raises(HTTPException) as exc:
        await service.embed_texts(["Synthetic"])
    assert exc.value.status_code == 503


class AsyncAdapter:
    """Real SQLite transaction behavior behind the route's async session protocol."""

    def __init__(self, db, failure=None):
        self.sync = db
        self.failure = failure

    def in_transaction(self):
        return self.sync.in_transaction()

    def add(self, row):
        self.sync.add(row)

    def add_all(self, rows):
        self.sync.add_all(rows)

    async def flush(self):
        if self.failure == "flush":
            raise RuntimeError("Synthetic flush failure")
        self.sync.flush()

    async def refresh(self, row):
        self.sync.refresh(row)

    async def rollback(self):
        self.sync.rollback()

    async def commit(self):
        if self.failure == "commit":
            raise RuntimeError("Synthetic commit failure")
        self.sync.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "provider", "flush", "commit"])
async def test_upload_boundaries_and_owned_cleanup(monkeypatch, tmp_path, failure):
    configure(monkeypatch, upload_dir=tmp_path, storage_backend="local")
    sentinel = tmp_path / "pre-existing.pdf"
    sentinel.write_bytes(b"Never remove an existing upload")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as sync:
        user = User(
            email="synthetic@example.invalid", full_name="Synthetic", password_hash="unused"
        )
        sync.add(user)
        sync.commit()
        sync.refresh(user)  # Authentication-like read transaction must also end.
        db = AsyncAdapter(sync, failure)

        async def text(self, path):
            assert not db.in_transaction(), "Transaction held during extraction"
            return "Synthetic financial document"

        async def embeddings(self, values):
            assert not db.in_transaction(), "Transaction held during embedding/retries"
            assert sync.scalar(select(func.count()).select_from(UploadedFile)) == 0
            sync.rollback()  # Only the test's assertion query opened this transaction.
            if failure == "provider":
                raise HTTPException(503, "Provider unavailable; retry")
            return [[0.0] * 1536 for _ in values]

        monkeypatch.setattr(DocumentIngestionService, "extract_document_text", text)
        monkeypatch.setattr(DocumentIngestionService, "embed_texts", embeddings)
        if failure:
            with pytest.raises((HTTPException, RuntimeError)):
                await upload_file(file(), user, db)
            assert sync.scalar(select(func.count()).select_from(UploadedFile)) == 0
            assert sync.scalar(select(func.count()).select_from(Embedding)) == 0
        else:
            result = await upload_file(file(), user, db)
            assert result.status == "indexed" and result.indexed == 1
            assert sync.scalar(select(func.count()).select_from(UploadedFile)) == 1
        assert sentinel.read_bytes() == b"Never remove an existing upload"
        generated = list((tmp_path / "staging").rglob("*.pdf"))
        assert len(generated) == (1 if failure in {None, "commit"} else 0)
    engine.dispose()


@pytest.mark.asyncio
async def test_staging_collision_never_appends_or_deletes_existing_file(monkeypatch, tmp_path):
    configure(monkeypatch, upload_dir=tmp_path, storage_backend="local")
    uid, file_id = uuid4(), uuid4()
    path = tmp_path / "staging" / str(uid) / f"{file_id}.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"Existing payload")
    monkeypatch.setattr("app.services.document_ingestion.uuid4", lambda: file_id)
    with pytest.raises(FileExistsError):
        await DocumentIngestionService().save_upload(uid, file())
    assert path.read_bytes() == b"Existing payload"


@pytest.mark.asyncio
async def test_conditional_s3_cleanup_only_deletes_owned_version(monkeypatch, tmp_path):
    import boto3

    from app.services.document_ingestion import StoredUpload

    configure(
        monkeypatch, upload_dir=tmp_path, storage_backend="s3", s3_upload_bucket="synthetic-bucket"
    )
    calls = []

    class S3:
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            calls.append(("put", kwargs["Key"]))
            return {"ETag": '"synthetic-etag"', "VersionId": "synthetic-version"}

        def delete_object(self, **kwargs):
            calls.append(("delete", kwargs))

    monkeypatch.setattr(boto3, "client", lambda name: S3())
    service = DocumentIngestionService()
    upload = await service.save_upload(uuid4(), file())
    await service.cleanup_upload(upload)
    assert calls[1][1]["Key"] == calls[0][1]
    assert calls[1][1]["IfMatch"] == '"synthetic-etag"'
    assert calls[1][1]["VersionId"] == "synthetic-version"
    foreign = tmp_path / "foreign.pdf"
    foreign.write_bytes(b"Existing")
    await service.cleanup_upload(
        StoredUpload(
            foreign, "s3://synthetic-bucket/existing", "existing.pdf", "application/pdf", ".pdf", 8
        )
    )
    assert foreign.read_bytes() == b"Existing"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_s3_collision_preserves_preexisting_object(monkeypatch, tmp_path):
    import boto3

    configure(
        monkeypatch, upload_dir=tmp_path, storage_backend="s3", s3_upload_bucket="synthetic-bucket"
    )

    class S3:
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            raise FileExistsError("Synthetic pre-existing object")

        def delete_object(self, **kwargs):
            pytest.fail("Existing object must not be deleted")

    monkeypatch.setattr(boto3, "client", lambda name: S3())
    with pytest.raises(FileExistsError):
        await DocumentIngestionService().save_upload(uuid4(), file())
    assert list(tmp_path.rglob("*.pdf")) == []


@pytest.mark.asyncio
async def test_local_retrieval_excludes_legacy_or_different_embedding_models(monkeypatch):
    from app.services.rag import RagService

    configure(monkeypatch, embedding_backend="local")
    from app.services.document_ingestion import settings as configured

    monkeypatch.setattr("app.services.rag.settings", configured)
    service = DocumentIngestionService()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    uid = uuid4()
    with Session(engine) as db:
        db.add(
            User(
                id=uid, email="model@example.invalid", full_name="Synthetic", password_hash="unused"
            )
        )
        vector = (await service.embed_texts(["coffee"]))[0]
        for model in ["deterministic-local-hash-v1", "remote-test-model", service.embedding_model]:
            db.add(
                Embedding(
                    user_id=uid,
                    source_type="upload",
                    source_id=uuid4(),
                    chunk_index=0,
                    chunk_text=model,
                    chunk_hash=model,
                    embedding=vector,
                    embedding_model=model,
                    embedding_dimensions=1536,
                    metadata_json={},
                )
            )
        db.flush()
        results = RagService(db).retrieve_chunks(uid, "coffee")
        assert service.embedding_model != "deterministic-local-hash-v1"
        assert [r.text for r in results] == [service.embedding_model]
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "provider", "storage", "flush", "commit", "cleanup"])
async def test_s3_cross_system_failure_boundaries(monkeypatch, tmp_path, failure):
    import boto3
    configure(monkeypatch, upload_dir=tmp_path, storage_backend="s3", s3_upload_bucket="synthetic-bucket")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    objects = {"pre-existing": b"Never remove"}
    with Session(engine, expire_on_commit=False) as sync:
        user = User(email="s3@example.invalid", full_name="Synthetic", password_hash="unused")
        sync.add(user)
        sync.commit()
        sync.refresh(user)
        db = AsyncAdapter(sync, "flush" if failure == "cleanup" else failure)
        class S3:
            def put_object(self, **kwargs):
                assert not db.in_transaction(), "Transaction held during S3 publication"
                assert kwargs["IfNoneMatch"] == "*" and kwargs["Key"] not in objects
                objects[kwargs["Key"]] = kwargs["Body"].read()
                if failure == "storage": raise TimeoutError("Uncertain storage acknowledgement")
                return {"ETag": '"created"', "VersionId": "created-version"}
            def delete_object(self, **kwargs):
                assert not db.in_transaction(), "Transaction held during storage cleanup"
                assert kwargs["Key"] != "pre-existing" and kwargs["IfMatch"] == '"created"'
                assert kwargs["VersionId"] == "created-version"
                if failure == "cleanup": raise OSError("Synthetic cleanup failure")
                objects.pop(kwargs["Key"])
        monkeypatch.setattr(boto3, "client", lambda name: S3())
        async def text(self, path):
            assert not db.in_transaction()
            return "Synthetic statement"
        async def embeddings(self, values):
            assert not db.in_transaction()
            if failure == "provider": raise HTTPException(503, "Provider unavailable; retry")
            return [[0.0] * 1536 for _ in values]
        monkeypatch.setattr(DocumentIngestionService, "extract_document_text", text)
        monkeypatch.setattr(DocumentIngestionService, "embed_texts", embeddings)
        if failure:
            with pytest.raises((HTTPException, RuntimeError, OSError)):
                await upload_file(file(), user, db)
            assert sync.scalar(select(func.count()).select_from(UploadedFile)) == 0
            assert sync.scalar(select(func.count()).select_from(Embedding)) == 0
        else:
            result = await upload_file(file(), user, db)
            row = sync.get(UploadedFile, result.file_id)
            assert row.user_id == user.id and row.storage_path.startswith("s3://synthetic-bucket/")
            assert sync.scalar(select(Embedding.user_id)) == user.id
        assert objects["pre-existing"] == b"Never remove"
        assert len(objects) == (1 if failure in {"provider", "flush"} else 2)
        assert list(tmp_path.rglob("*.pdf")) == []
    engine.dispose()


@pytest.mark.asyncio
async def test_open_circuit_does_not_extend_the_provider_failure_window(monkeypatch):
    configure(monkeypatch)
    class Circuit:
        def before_call(self): raise CircuitOpenError("Synthetic open circuit")
        def record_failure(self): pytest.fail("A blocked call is not a new provider failure")
    monkeypatch.setattr("app.services.document_ingestion.openai_circuit", Circuit())
    with pytest.raises(HTTPException) as exc:
        await DocumentIngestionService().embed_texts(["Synthetic"])
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_remote_provider_cannot_substitute_a_different_model(monkeypatch):
    configure(monkeypatch)
    service = DocumentIngestionService()
    async def create(**kwargs):
        return SimpleNamespace(model="unexpected-model", data=[SimpleNamespace(index=0, embedding=[0.0] * 1536)])
    service._openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    with pytest.raises(HTTPException) as exc:
        await service.embed_texts(["Synthetic"])
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_valid_remote_response_preserves_input_order(monkeypatch):
    configure(monkeypatch)
    service = DocumentIngestionService()
    async def create(**kwargs):
        return SimpleNamespace(model=service.embedding_model, data=[
            SimpleNamespace(index=1, embedding=[2.0] * 1536),
            SimpleNamespace(index=0, embedding=[1.0] * 1536)])
    service._openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    vectors = await service.embed_texts(["first", "second"])
    assert [v[0] for v in vectors] == [1.0, 2.0]


def test_rag_does_not_query_with_an_unexpected_remote_model(monkeypatch):
    from app.services.rag import RagService
    service = object.__new__(RagService)
    service._embedding_backend = "openai"
    service._embedding_model = "expected-model"
    class NoDatabaseAccess:
        def get_bind(self): pytest.fail("Unexpected-model embeddings reached the database query")
    service.db = NoDatabaseAccess()
    def create(**kwargs):
        return SimpleNamespace(model="unexpected-model", data=[SimpleNamespace(index=0, embedding=[0.0] * 1536)])
    service._openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr("app.services.rag.openai_circuit", CircuitBreaker(5, 30))
    assert service.retrieve_chunks(uuid4(), "Synthetic") == []
