"""Run the synthetic retrieval suite against a dedicated local PostgreSQL database."""

import argparse
import asyncio
import json
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from hashlib import sha256
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base, get_async_db, get_db
from app.core.security import TokenType, create_token
from app.main import create_app
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding
from app.models.user import User
from app.services.document_ingestion import DocumentIngestionService
from app.services.document_qa import DocumentQAService
from app.services.llm import LLMService
from app.services.rag import DEFAULT_MIN_SCORE, LOCAL_EMBEDDING_MODEL, RagService
from evaluation.evidence_mapping import StoredChunk, align_chunks, map_evidence
from evaluation.pdf_fixture import RENDERER_VERSION, render_pdf, verify_pdf
from evaluation.retrieval_metrics import METRICS, score_at_k
from evaluation.schemas import DATA_DIRECTORY, load_document_dataset

REPO = Path(__file__).resolve().parents[2]
PARAMETERS = signature(DocumentIngestionService.chunk_text).parameters
CHUNK_SIZE = PARAMETERS["chunk_tokens"].default
OVERLAP = PARAMETERS["overlap_tokens"].default


def validate_test_database_url(raw: str | URL | None) -> URL:
    if not raw:
        raise ValueError("Set TEST_DATABASE_URL to a dedicated local PostgreSQL/pgvector database")
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        raise ValueError("Invalid test database URL") from None
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or url.query
    ):
        raise ValueError("Use a loopback postgresql+psycopg test URL without connection overrides")
    return url


@asynccontextmanager
async def isolated_database(url):
    schema = f"rag_eval_{uuid4().hex}"
    hostaddr = "127.0.0.1" if url.host == "localhost" else url.host
    connection = {"hostaddr": hostaddr, "connect_timeout": 5}
    admin = create_engine(url, connect_args=connection)
    try:
        with admin.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = async_engine = None
        try:
            options = {**connection, "options": f"-csearch_path={schema},public"}
            engine = create_engine(url, connect_args=options)
            async_engine = create_async_engine(url, connect_args=options)
            Base.metadata.create_all(engine, checkfirst=False)
            yield engine, async_engine
        finally:
            if async_engine is not None:
                await async_engine.dispose()
            if engine is not None:
                engine.dispose()
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        admin.dispose()


class TimedRagService(RagService):
    embedding_ms: float | None = None

    def embed_text(self, value):
        started = perf_counter()
        try:
            return super().embed_text(value)
        finally:
            self.embedding_ms = (perf_counter() - started) * 1000


def rank_case(engine, principal, scope, question, k, threshold, chunk_lookup):
    with Session(engine) as db:
        authorized = DocumentQAService(db, principal)._load_authorized_documents(scope)
        db.rollback()
        if set(authorized) != {str(document_id) for document_id in scope}:
            raise ValueError("Unexpected authorized document scope")
        rag = TimedRagService(db)
        sql_ms = None
        sql_started = None

        def before_cursor(_conn, _cursor, statement, *_args):
            nonlocal sql_started
            if "<=>" in statement:
                sql_started = perf_counter()

        def after_cursor(_conn, _cursor, statement, *_args):
            nonlocal sql_ms
            if "<=>" in statement and sql_started is not None:
                sql_ms = (perf_counter() - sql_started) * 1000

        event.listen(engine, "before_cursor_execute", before_cursor)
        event.listen(engine, "after_cursor_execute", after_cursor)
        started = perf_counter()
        try:
            rows = rag.retrieve_chunks(
                principal,
                question,
                limit=k,
                document_ids=scope,
                min_score=threshold,
                raise_provider_errors=True,
            )
            retrieval_ms = (perf_counter() - started) * 1000
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor)
            event.remove(engine, "after_cursor_execute", after_cursor)
        if sql_ms is None:
            raise ValueError("Expected pgvector query was not observed")
        ranked = []
        for rank, row in enumerate(rows, start=1):
            stored = chunk_lookup.get(row.embedding_id)
            if stored is None:
                raise ValueError("Unmapped retrieval result")
            document, document_id, owner, index, digest, chunk_text, span = stored
            if (
                row.source_id != document_id
                or row.source_type != "upload"
                or owner != principal
                or document_id not in scope
                or row.chunk_index != index
                or row.text != chunk_text
                or row.score is None
                or row.score < threshold
            ):
                raise ValueError("Retrieved chunk violated verified scope or provenance")
            ranked.append(
                {
                    "rank": rank,
                    "document": document,
                    "chunk_index": index,
                    "chunk_sha256": digest,
                    "span": span,
                    "score": row.score,
                }
            )
    return ranked, {
        "query_embedding_ms": rag.embedding_ms,
        "vector_sql_execute_ms": sql_ms,
        "retrieval_ms": retrieval_ms,
    }


async def ingest_corpus(bundle, http, headers, engine, directory):
    service = DocumentIngestionService()
    ids = {}
    passages = {}
    chunk_lookup = {}
    for doc in bundle.corpus.documents:
        source = (DATA_DIRECTORY / "corpus" / doc.path).read_bytes()
        if sha256(source).hexdigest() != doc.revision_sha256:
            raise ValueError("Corpus changed after validation")
        original = source.decode("utf-8")
        pdf = render_pdf(original)
        path = directory / "round-trip.pdf"
        path.write_bytes(pdf)
        anchors = {passage.key: passage.text for passage in doc.evidence}
        extracted = await verify_pdf(service, path, original, list(anchors.values()))
        spans = map_evidence(extracted, anchors)
        passages.update({(doc.key, key): span for key, span in spans.items()})
        # Source ID is the production SQL tie breaker before chunk index.
        # Inject a fixed synthetic ID at the upload boundary to stabilize tied scores.
        doc_id = uuid5(NAMESPACE_URL, f"finsight-retrieval/document/{doc.key}")
        with patch("app.api.routes.uploads.uuid4", return_value=doc_id):
            response = await http.post(
                "/api/uploads",
                headers=headers[doc.owner],
                files={"file": (f"{doc.key}.pdf", pdf, "application/pdf")},
            )
        response.raise_for_status()
        if UUID(response.json()["file_id"]) != doc_id:
            raise ValueError("Unexpected upload identity")
        ids[doc.key] = doc_id
        with Session(engine) as db:
            rows = db.scalars(
                select(Embedding)
                .where(Embedding.source_id == doc_id)
                .order_by(Embedding.chunk_index)
            ).all()
            geometry = align_chunks(
                extracted,
                [StoredChunk(row.chunk_index, row.chunk_text, row.chunk_hash) for row in rows],
                chunk_size=CHUNK_SIZE,
                overlap=OVERLAP,
            )
            for row in rows:
                if (
                    row.embedding_model != LOCAL_EMBEDDING_MODEL
                    or row.embedding_dimensions != EMBEDDING_DIMENSIONS
                ):
                    raise ValueError("Unexpected persisted embedding configuration")
                chunk_lookup[row.id] = (
                    doc.key,
                    doc_id,
                    row.user_id,
                    row.chunk_index,
                    row.chunk_hash,
                    row.chunk_text,
                    geometry[row.chunk_index],
                )
    return ids, passages, chunk_lookup


def track_for(case):
    if case.answerability == "unauthorized":
        return "authorization"
    if case.answerability == "conflicting":
        return "conflict"
    if case.relevant_evidence:
        return "retrieval"
    return "diagnostic"


async def evaluate_cases(bundle, http, headers, users, engine, corpus, k, threshold):
    ids, passages, chunk_lookup = corpus
    results = []
    for case in bundle.dataset.cases:
        track = track_for(case)
        row = {"id": case.id, "track": track}
        scope = [ids[key] for key in case.document_scope]
        try:
            if track == "authorization":
                with (
                    patch.object(
                        RagService,
                        "retrieve_chunks",
                        side_effect=AssertionError("Unexpected retrieval"),
                    ) as retrieval,
                    patch.object(
                        LLMService,
                        "synthesize_document_answer_result",
                        side_effect=AssertionError("Unexpected generation"),
                    ) as generation,
                ):
                    response = await http.post(
                        "/api/documents/ask",
                        headers=headers[case.principal],
                        json={
                            "question": case.question,
                            "document_ids": [str(value) for value in scope],
                        },
                    )
                passed = (
                    response.status_code == case.expected_http_status
                    and not retrieval.called
                    and not generation.called
                )
                row.update(
                    status="ok" if passed else "error",
                    authorization={
                        "http_status": response.status_code,
                        "retrieval_called": retrieval.called,
                        "generation_called": generation.called,
                        "passed": passed,
                    },
                    metrics=dict.fromkeys(METRICS),
                )
            else:
                ranked, timing = rank_case(
                    engine, users[case.principal], scope, case.question, k, threshold, chunk_lookup
                )
                keys = [(ref.document_key, ref.evidence_key) for ref in case.relevant_evidence]
                metrics = score_at_k(
                    [(item["document"], item["span"]) for item in ranked],
                    {key: passages[key] for key in keys},
                    k,
                )
                row.update(
                    status="ok",
                    retrieved_count=len(ranked),
                    results=ranked,
                    metrics=metrics,
                    latency=timing,
                )
        except Exception as exc:  # noqa: BLE001 - report every case failure without payloads.
            row.update(status="error", error=type(exc).__name__, metrics=dict.fromkeys(METRICS))
        results.append(row)
    return results


def aggregates(results):
    groups = {}
    for track in ("retrieval", "conflict"):
        expected = [row for row in results if row["track"] == track]
        measured = [row for row in expected if row["status"] == "ok"]
        groups[track] = {
            "applicable_cases": len(expected),
            "measured_cases": len(measured),
            "failed_cases": len(expected) - len(measured),
            "metrics": {
                name: sum(row["metrics"][name] for row in measured) / len(expected)
                if expected and len(measured) == len(expected)
                else None
                for name in METRICS
            },
        }
    return groups


async def evaluate_retrieval(url, k=5, min_score=DEFAULT_MIN_SCORE):
    """Evaluate only a validated, explicitly supplied dedicated local test URL."""
    url = validate_test_database_url(url)
    if not 1 <= k <= 20 or not -1 <= min_score <= 1:
        raise ValueError("Use k in 1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“20 and min_score in [-1, 1]")
    threshold = RagService.normalize_min_score(min_score)
    bundle = load_document_dataset()
    with (
        TemporaryDirectory(prefix="finsight-retrieval-") as temporary,
        patch.multiple(
            settings,
            upload_dir=Path(temporary),
            storage_backend="local",
            embedding_backend="local",
            rate_limit_backend="memory",
        ),
        patch("app.services.llm.create_openai_client", return_value=None),
    ):
        async with isolated_database(url) as (engine, async_engine):
            owners = sorted(
                {doc.owner for doc in bundle.corpus.documents}
                | {case.principal for case in bundle.dataset.cases}
            )
            users = {
                owner: uuid5(NAMESPACE_URL, f"finsight-retrieval/user/{owner}") for owner in owners
            }
            with Session(engine) as db:
                db.add_all(
                    [
                        User(
                            id=identity,
                            email=f"{owner}@example.invalid",
                            full_name="Synthetic",
                            password_hash="unused",
                        )
                        for owner, identity in users.items()
                    ]
                )
                db.commit()
                extension = db.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                hnsw = db.scalar(
                    text(
                        "SELECT EXISTS (SELECT FROM pg_indexes WHERE schemaname = current_schema() "
                        "AND tablename = 'embeddings' AND indexdef LIKE '%USING hnsw%')"
                    )
                )

            def sync_db():
                with Session(engine, expire_on_commit=False) as db:
                    yield db

            async def async_db():
                async with AsyncSession(async_engine, expire_on_commit=False) as db:
                    yield db

            app = create_app()
            app.dependency_overrides[get_db] = sync_db
            app.dependency_overrides[get_async_db] = async_db
            headers = {
                owner: {"Authorization": f"Bearer {create_token(identity, TokenType.ACCESS)}"}
                for owner, identity in users.items()
            }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as http:
                corpus = await ingest_corpus(bundle, http, headers, engine, Path(temporary))
                results = await evaluate_cases(
                    bundle, http, headers, users, engine, corpus, k, threshold
                )
    errors = [row["id"] for row in results if row["status"] != "ok"]
    commit = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        )
    ).strip()
    dirty = bool(
        (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "status", "--porcelain"], cwd=REPO, text=True
            )
        ).strip()
    )
    return {
        "report_version": 1,
        "git_commit": commit,
        "working_tree_dirty": dirty,
        "mode": "deterministic_local",
        "dataset_schema_version": bundle.dataset.schema_version,
        "dataset_version": bundle.dataset.dataset_version,
        "corpus_version": bundle.corpus.corpus_version,
        "corpus_hashes": {doc.key: doc.revision_sha256 for doc in bundle.corpus.documents},
        "pdf_renderer": RENDERER_VERSION,
        "embedding": {
            "backend": "local",
            "model": LOCAL_EMBEDDING_MODEL,
            "dimensions": EMBEDDING_DIMENSIONS,
        },
        "database": {
            "backend": "postgresql",
            "pgvector_version": extension,
            "pgvector_used": any("latency" in row for row in results),
            "hnsw_present": hnsw,
        },
        "chunking": {"units": "whitespace", "size": CHUNK_SIZE, "overlap": OVERLAP},
        "retrieval": {"k": k, "min_score": threshold},
        "latency_boundaries": {
            "query_embedding_ms": "embed_text only",
            "vector_sql_execute_ms": "DBAPI cursor execute, excluding subsequent fetch and hydration",
            "retrieval_ms": "retrieve_chunks through result materialization",
        },
        "cases": results,
        "aggregates": aggregates(results),
        "skips": [],
        "errors": errors,
        "complete": not errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    args = parser.parse_args()
    try:
        url = validate_test_database_url(os.getenv("TEST_DATABASE_URL"))
    except (ValueError, TypeError):
        parser.error("Set TEST_DATABASE_URL to a dedicated loopback postgresql+psycopg database")
    # The CLI reserves stdout for the report and suppresses application logs.
    logging.disable(logging.CRITICAL)
    try:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            report = runner.run(evaluate_retrieval(url, args.k, args.min_score))
    except Exception as exc:  # noqa: BLE001 - sanitize failed runs at the CLI boundary.
        report = {
            "report_version": 1,
            "complete": False,
            "skips": [],
            "errors": [{"phase": "setup_or_ingestion", "kind": type(exc).__name__}],
        }
    print(json.dumps(report, indent=2, allow_nan=False))
    return int(not report["complete"])


if __name__ == "__main__":
    raise SystemExit(main())
