"""Isolated ASGI experiment using production routes, services and SDK."""

import json
from contextlib import asynccontextmanager
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import httpx
from openai import AsyncOpenAI, OpenAI
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.routes import uploads
from app.core.config import settings
from app.core.database import get_async_db, get_db
from app.core.openai_resilience import CircuitBreaker
from app.core.security import TokenType, create_token
from app.main import create_app
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding
from app.models.user import User
from app.services import document_ingestion, llm, rag
from evaluation.answer_rubric import load_answer_rubric
from evaluation.answer_runner import CapturedDraft, verified_citations
from evaluation.evidence_mapping import StoredChunk, align_chunks, map_evidence
from evaluation.pdf_fixture import render_pdf, verify_pdf
from evaluation.real_model_contract import ORIGIN, canonical, digest
from evaluation.real_model_grading import Adjudication, grade
from evaluation.real_model_provider import (
    COMPLETIONS,
    AsyncTransport,
    Boundary,
    Phase,
    SafetyError,
    SyncTransport,
    observation_state,
    unit_key,
)
from evaluation.real_model_runner import atomic_write
from evaluation.retrieval_runner import (
    CHUNK_SIZE,
    OVERLAP,
    isolated_database,
    validate_test_database_url,
)
from evaluation.schemas import DATA_DIRECTORY, load_document_dataset


@asynccontextmanager
async def fixture(bundle, url):
    url = validate_test_database_url(url)
    if not url.database.startswith("finsight_eval_"):
        raise SafetyError("Use a dedicated finsight_eval_* database")
    admin = create_engine(
        url,
        connect_args={
            "hostaddr": "127.0.0.1" if url.host == "localhost" else url.host,
            "connect_timeout": 5,
        },
    )
    try:
        with admin.connect() as conn:
            if not conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
            ):
                raise SafetyError("Install pgvector on the dedicated database before the run")
    finally:
        admin.dispose()
    async with isolated_database(url) as (engine, async_engine):
        principals = {
            doc.owner: uuid5(NAMESPACE_URL, f"finsight-real-model/user/{doc.owner}")
            for doc in bundle.corpus.documents
        }
        with Session(engine) as session:
            session.add_all(
                User(
                    id=key,
                    email=f"{owner}@example.invalid",
                    full_name="Synthetic",
                    password_hash="unused",
                )
                for owner, key in principals.items()
            )
            session.commit()

        def sync_db():
            with Session(engine, expire_on_commit=False) as session:
                yield session

        async def async_db():
            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_db] = sync_db
        app.dependency_overrides[get_async_db] = async_db
        headers = {
            owner: {"Authorization": f"Bearer {create_token(key, TokenType.ACCESS)}"}
            for owner, key in principals.items()
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://evaluation.invalid",
            trust_env=False,
        ) as http:
            yield http, headers, principals, engine


async def ingest(bundle, http, headers, principals, engine, directory, boundary):
    ids, passages, persisted = {}, {}, {}
    service = document_ingestion.DocumentIngestionService()
    for document in bundle.corpus.documents:
        source = (DATA_DIRECTORY / "corpus" / document.path).read_bytes()
        if sha256(source).hexdigest() != document.revision_sha256:
            raise SafetyError("Synthetic fixture changed")
        original = source.decode()
        pdf = render_pdf(original)
        path = directory / "round-trip.pdf"
        path.write_bytes(pdf)
        anchors = {item.key: item.text for item in document.evidence}
        extracted = await verify_pdf(service, path, original, list(anchors.values()))
        spans = map_evidence(extracted, anchors)
        passages.update({(document.key, key): span for key, span in spans.items()})
        chunks = [chunk.text for chunk in service.chunk_text(extracted)]
        doc_id = uuid5(NAMESPACE_URL, f"finsight-real-model/document/{document.key}")
        with (
            boundary.during(Phase(f"ingest:{document.key}", embedding_input=chunks)),
            patch.object(uploads, "uuid4", return_value=doc_id),
        ):
            response = await http.post(
                "/api/uploads",
                headers=headers[document.owner],
                files={"file": (f"{document.key}.pdf", pdf, "application/pdf")},
            )
        if response.status_code not in (200, 201) or response.json().get("file_id") != str(doc_id):
            raise SafetyError("Synthetic ingestion failed")
        ids[document.key] = doc_id
        with Session(engine) as session:
            rows = session.scalars(
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
                    row.user_id != principals[document.owner]
                    or row.embedding_model != boundary.profile.embedding_model
                    or row.embedding_dimensions != EMBEDDING_DIMENSIONS
                ):
                    raise SafetyError("Unexpected persisted embedding ownership or model")
                ref = f"doc:{doc_id}:chunk:{row.chunk_index}"
                persisted[ref] = (
                    document.key,
                    doc_id,
                    row.user_id,
                    row.chunk_index,
                    row.chunk_hash,
                    row.chunk_text,
                    geometry[row.chunk_index],
                )
    return ids, passages, persisted


async def ask(http, headers, principals, case, unit, ids, persisted, boundary):
    authorized = case.expected_outcome != "authorization_denied"
    phase = Phase(unit, embedding_input=[case.question] if authorized else None)
    ranked, prompt = [], {}
    retrieval_called = False
    retrieve = rag.RagService.retrieve_chunks
    build = llm.LLMService._build_document_prompt

    def verify(ref, value):
        row = persisted.get(ref)
        if (
            row is None
            or row[0] not in case.document_scope
            or (row[2] != principals[case.principal] or row[5] != value)
        ):
            raise SafetyError("Unexpected chunk origin")
        return row

    def observed_retrieve(service, *args, **kwargs):
        nonlocal retrieval_called
        retrieval_called = True
        if not authorized:
            raise SafetyError("Forbidden scope reached retrieval")
        rows = retrieve(service, *args, **kwargs)
        for row in rows:
            ref = f"doc:{row.source_id}:chunk:{row.chunk_index}"
            stored = verify(ref, row.text)
            ranked.append(
                {
                    "reference": ref,
                    "document": stored[0],
                    "span": stored[6],
                    "chunk_sha256": stored[4],
                    "score": row.score,
                }
            )
        return rows

    def observed_prompt(service, question, chunks):
        if not authorized or question != case.question:
            raise SafetyError("Unexpected generation scope")
        for chunk in chunks:
            verify(chunk["reference"], chunk["text"])
            prompt[chunk["reference"]] = chunk["text"]
        phase.prompt = build(service, question, chunks)
        return phase.prompt

    response, public = None, {}
    error = None
    with (
        boundary.during(phase),
        patch.object(rag.RagService, "retrieve_chunks", observed_retrieve),
        patch.object(llm.LLMService, "_build_document_prompt", observed_prompt),
    ):
        try:
            response = await http.post(
                "/api/documents/ask",
                headers=headers[case.principal],
                json={
                    "question": case.question,
                    "document_ids": [str(ids[key]) for key in case.document_scope],
                    "limit": boundary.profile.limit,
                    "min_score": boundary.profile.min_score,
                },
            )
            public = response.json()
            if authorized and (
                response.status_code != 200 or public.get("status") == "provider_error"
            ):
                error = boundary.failure or "application_response_error"
        except (SafetyError, httpx.HTTPError, ValueError):
            error = boundary.failure or "evaluation_contract_error"

    attempts = sorted(boundary.seen)
    status = response.status_code if response is not None else None
    verified = {}
    if not authorized:
        if (
            retrieval_called
            or attempts
            or status != 404
            or public != {"detail": "Document not found"}
        ):
            error = "authorization_failure"
            public = {}
    elif not error:
        try:
            verified = verified_citations(
                public, prompt, persisted, case.document_scope, principals[case.principal]
            )
        except (KeyError, ValueError, TypeError):
            error = "citation_validation_failure"
            public = {}

    raw = boundary.journal.db.execute(
        "SELECT response FROM attempts WHERE unit=? AND endpoint=? AND state='confirmed'",
        (unit, COMPLETIONS),
    ).fetchone()
    parsed = None
    if raw and raw[0]:
        try:
            content = json.loads(raw[0])["body"]["choices"][0]["message"]["content"]
            parsed = CapturedDraft.model_validate_json(content).model_dump(mode="json")
        except (KeyError, TypeError, IndexError, ValueError):
            if status == 200 and public.get("status") == "provider_error" and not boundary.failure:
                error = "model_response_parse_failure"
            else:
                error = error or "evaluation_contract_error"
    return {
        "schema_version": 1,
        "http_status": status,
        "public": public,
        "error": error,
        "ranking": ranked,
        "prompt_references": list(prompt),
        "prompt_sha256": digest(phase.prompt) if phase.prompt else None,
        "retrieval_called": retrieval_called,
        "verified_citations": verified,
        "provider_attempts": attempts,
        "parsed_draft": parsed,
    }


def published_observation(row):
    return row["observation"] | {
        "case": row["case"],
        "repetition": row["repetition"],
        "state": observation_state(row["observation"]["error"]),
    }


def review_records(directory, journal, identity):
    path = directory / "adjudications.jsonl"
    if not path.exists():
        return b""
    payload = path.read_bytes()
    observed = {
        digest(published_observation(json.loads(body))): json.loads(body)["grade"]
        for (body,) in journal.db.execute("SELECT body FROM observations")
    }
    seen = set()
    for line in payload.splitlines():
        review = Adjudication.model_validate_json(line)
        key = (review.observation_sha256, review.dimension, review.reviewer)
        if (
            review.rubric_sha256 != identity["plan"]["rubric_sha256"]
            or review.dimension not in observed.get(review.observation_sha256, {})
            or key in seen
        ):
            raise SafetyError("Invalid or duplicate adjudication reference")
        seen.add(key)
    return payload


def artifacts(directory, journal, identity, run_error, reused=0):
    observations = [
        json.loads(row[0])
        for row in journal.db.execute("SELECT body FROM observations ORDER BY unit")
    ]
    attempts = []
    for (
        unit,
        endpoint,
        payload,
        input_tokens,
        output_tokens,
        cost,
        response,
        usage,
        state,
        error,
    ) in journal.db.execute(
        "SELECT unit, endpoint, payload, input_tokens, output_tokens, cost, response, usage, state, error FROM attempts ORDER BY unit,endpoint"
    ):
        body = json.loads(response) if response else None
        attempts.append(
            {
                "unit": unit,
                "endpoint": endpoint,
                "payload_sha256": payload,
                "reserved_input_tokens": input_tokens,
                "reserved_output_tokens": output_tokens,
                "reserved_cost": cost,
                "usage_tokens": int(usage) if usage is not None else None,
                "state": state,
                "error": error,
                "confirmed": state == "confirmed",
                "model": body["body"].get("model") if body and body["body"] else None,
                "request_id": body["request_id"] if body else None,
                "http_status": body["status"] if body else None,
            }
        )
    distributions = {}
    for record in observations:
        case = distributions.setdefault(record["case"], {})
        for key, value in record["grade"].items():
            if isinstance(value, str):
                counts = case.setdefault(key, {})
                counts[value] = counts.get(value, 0) + 1
    totals = {}
    for row in observations:
        grade_row = row["grade"]
        metrics = (grade_row["retrieval_metrics"] or {}) | {
            "required_fact_coverage": grade_row["required_fact_coverage"]
        }
        for name, value in metrics.items():
            if value is not None:
                total = totals.setdefault(name, {"sum": 0.0, "denominator": 0})
                total["sum"] += value
                total["denominator"] += 1
    counts = dict(journal.db.execute("SELECT state, count(*) FROM observations GROUP BY state"))
    planned = len(identity["plan"]["units"])
    successful = counts.get("successful", 0)
    failed = counts.get("operational_failure", 0)
    summary = {
        "schema_version": 2,
        "run_error": run_error,
        "aggregates": {
            name: {"mean": item["sum"] / item["denominator"], "denominator": item["denominator"]}
            for name, item in totals.items()
        },
        "manifest_sha256": digest(identity),
        "planned": planned,
        "terminal_observations": successful + failed,
        "successful_evaluations": successful,
        "operational_failures": failed,
        "incomplete_units": planned - successful - failed,
        "uncertain_attempts": sum(row["state"] == "uncertain" for row in attempts),
        "reserved_attempts": sum(row["state"] == "reserved" for row in attempts),
        "rejected_attempts": sum(row["state"] == "rejected" for row in attempts),
        "reused_confirmed_responses": reused,
        "per_case": distributions,
        "requests": attempts,
        "reserved_requests": len(attempts),
        "reserved_tokens": sum(
            row["reserved_input_tokens"] + row["reserved_output_tokens"] for row in attempts
        ),
        "reserved_cost": str(sum((Decimal(row["reserved_cost"]) for row in attempts), Decimal(0))),
        "usage_unknown": sum(row["usage_tokens"] is None for row in attempts),
        "known_usage_tokens": sum(row["usage_tokens"] or 0 for row in attempts),
    }
    files = {
        "observations.jsonl": [published_observation(row) for row in observations],
        "grades.jsonl": [
            row["grade"]
            | {
                "case": row["case"],
                "repetition": row["repetition"],
                "observation_sha256": digest(published_observation(row)),
            }
            for row in observations
        ],
    }
    summary["artifact_sha256"] = {}
    for name, rows in files.items():
        payload = b"".join(canonical(row) + b"\n" for row in rows)
        atomic_write(directory / name, payload)
        summary["artifact_sha256"][name] = sha256(payload).hexdigest()
    summary["artifact_sha256"]["adjudications.jsonl"] = sha256(
        review_records(directory, journal, identity)
    ).hexdigest()
    if not (directory / "adjudications.jsonl").exists():
        atomic_write(directory / "adjudications.jsonl", b"")
    atomic_write(directory / "summary.json", canonical(summary))
    return summary


async def execute(
    profile, journal, credential, database, directory, identity, *, sync_send=None, async_send=None
):
    if (sync_send is None) != (async_send is None):
        raise SafetyError("Simulation must replace both provider transports")
    bundle = load_document_dataset()
    rubrics = {case.id: case for case in load_answer_rubric(bundle).cases}
    cases = {case.id: case for case in bundle.dataset.cases}
    units = identity["plan"]["units"]
    journal.assert_resumable({unit_key(entry) for entry in units})
    review_records(directory, journal, identity)
    recorded = {unit for (unit,) in journal.db.execute("SELECT unit FROM observations")}
    pending = [entry for entry in units if unit_key(entry) not in recorded]
    if not pending:
        return artifacts(directory, journal, identity, None)
    boundary = Boundary(profile, journal, credential)
    run_error = None
    sync_client = OpenAI(
        api_key=credential,
        base_url=ORIGIN + "/v1",
        max_retries=0,
        timeout=profile.timeout_seconds,
        http_client=httpx.Client(
            transport=SyncTransport(boundary, sync_send), follow_redirects=False, trust_env=False
        ),
    )
    async_client = AsyncOpenAI(
        api_key=credential,
        base_url=ORIGIN + "/v1",
        max_retries=0,
        timeout=profile.timeout_seconds,
        http_client=httpx.AsyncClient(
            transport=AsyncTransport(boundary, async_send), follow_redirects=False, trust_env=False
        ),
    )
    try:
        with TemporaryDirectory(prefix="finsight-real-model-") as temp:
            upload_dir = Path(temp)
            circuit = CircuitBreaker(3, 60)
            with (
                patch.multiple(
                    settings,
                    upload_dir=upload_dir,
                    storage_backend="local",
                    rate_limit_backend="memory",
                    openai_model=profile.model,
                    embedding_backend=profile.embedding_backend,
                    openai_embedding_model=profile.embedding_model,
                ),
                patch.object(llm, "create_openai_client", return_value=sync_client),
                patch.object(rag, "create_openai_client", return_value=sync_client),
                patch.object(
                    document_ingestion, "create_async_openai_client", return_value=async_client
                ),
                patch.object(llm, "openai_circuit", circuit),
                patch.object(rag, "openai_circuit", circuit),
                patch.object(document_ingestion, "openai_circuit", circuit),
            ):
                async with fixture(bundle, database) as (
                    http,
                    headers,
                    principals,
                    engine,
                ):
                    ids, passages, persisted = await ingest(
                        bundle, http, headers, principals, engine, upload_dir, boundary
                    )
                    for entry in pending:
                        unit = unit_key(entry)
                        case = cases[entry["case"]]
                        observation = await ask(
                            http, headers, principals, case, unit, ids, persisted, boundary
                        )
                        keys = [
                            (item.document_key, item.evidence_key)
                            for item in case.relevant_evidence
                        ]
                        gold = (
                            {}
                            if case.expected_outcome == "authorization_denied"
                            else {key: passages[key] for key in keys}
                        )
                        journal.observe(
                            unit,
                            entry
                            | {
                                "observation": observation,
                                "grade": grade(observation, rubrics[case.id], gold, profile.limit),
                            },
                        )
                        if observation_state(observation["error"]) == "incomplete":
                            run_error = observation["error"]
                            break
    except BaseException:
        run_error = boundary.failure or "incomplete_execution"
        raise
    finally:
        sync_client.close()
        await async_client.close()
        summary = artifacts(directory, journal, identity, run_error, boundary.reused)
    return summary
