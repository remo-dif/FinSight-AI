# AI/RAG evaluation and observability baseline

Date: 2026-10-29. Branch: `feature/ai-rag-evaluation`.
Base: latest `origin/master`, `a1ac9fb`, confirmed as the default branch after fetch.
Implementation checkpoint: `2e51c7a5f5c8cd456da12030f09575bf3a91ba26`.

## 1. Verified architecture

```text
User request -> bearer authentication + session ownership
  -> query embedding -> user/model/dimension-filtered retrieval
  -> LangGraph supervisor -> one of six financial tools -> immutable evidence snapshot
  -> LLM selects fact keys ONLY -> deterministic reviewer renders financial answer
  -> answer + review + tool_results -> atomic chat-message/audit persistence

Upload -> authentication -> staging -> parse -> embeddings (PDF/image path only)
  -> final storage -> short DB persistence transaction -> ingestion audit
CSV -> validated transactions + investigation cases, NOT vector indexing
```

Links below refer to the implementation checkpoint, not inferred dependency capabilities.

| Stage | Classification and evidence |
| --- | --- |
| Authentication/session ownership | Implemented and tested: [chat route](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/api/routes/chat.py#L24) checks ownership before generation and again before persistence. Existing authorization regressions remain intact. |
| Provider configuration | Implemented; live behavior insufficiently tested: [client/circuit policy](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/core/openai_resilience.py#L76), configured OpenAI chat and embedding models. All new automated calls are mocked. Explicit local hash embeddings are a separate configured mode, not a remote-provider fallback. |
| Document parsing | Text PDF and CSV implemented/tested; image OCR partially implemented: [extraction](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/services/document_ingestion.py#L510) indexes image dimensions/placeholder text, not recognized image content. Scanned PDF OCR is not implemented. |
| Embedding/indexing | Implemented and tested: [preparation](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/services/document_ingestion.py#L228) and embedding records preserve source/owner/model/dimensions. Providers run before persistence transactions. |
| Vector retrieval | Implemented and tested: [retrieval](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/services/rag.py#L97) uses pgvector cosine search or SQLite cosine ranking with user/model/dimension filters. No relevance cutoff/reranker exists. |
| LangGraph/context | Implemented and tested: [workflow](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/agents/orchestrator.py#L88) routes to six financial specialists. Retrieved text is present in state, but the financial generation path deliberately bypasses document prose. Previous chat messages are persisted, not loaded into model context. |
| Answer generation/review | Financial mode implemented and tested: [claim selection](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/services/llm.py#L30) sends only allowed fact keys; [review](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/backend/app/services/financial_review.py#L44) replaces invalid prose/IDs with deterministic financial explanations. General document Q&A is not implemented in this public workflow. |
| Citations | Partially implemented: transaction references exist in `tool_results._evidence`; no document claim-to-source citation contract exists. The [chat UI](https://github.com/remo-dif/FinSight-AI/blob/2e51c7a5f5c8cd456da12030f09575bf3a91ba26/frontend/src/components/assistant/chat-panel.tsx#L40) displays answer/review, not the structured reference metadata. |
| Persistence/audit | Implemented and tested: two chat messages and `ai.chat` audit are persisted after provider calls. Full tool evidence, selected documents, token usage and prompts are not persisted as chat artifacts. No tracing platform is required. |

## 2. End-to-end findings

The new service-backed integration uses real HTTP ASGI routing, real JWT checks,
an actual one-page PDF generated with stdlib, CSV parsing, filesystem staging,
PostgreSQL/pgvector, both sync/async database sessions and persistent audit rows.
Only OpenAI SDK embedding/chat responses are replaced with deterministic fakes.

It verifies: authenticated upload; correct owner; indexed PDF chunks; query
retrieval; exclusion of another user's document; trusted transaction references;
deterministic rejection of a fabricated fraud assertion; chat/audit persistence;
foreign-session rejection before provider calls; no transaction during mocked
provider calls; correlation and content-free telemetry across thread boundaries.

The eight-stage document-answer workflow is therefore **not fully implemented**:
retrieval exists, but document-grounded free-form answers and document citations
do not. This cycle measures that gap rather than adding a new Q&A subsystem.

## 3. Dataset and runner

Dataset: `backend/evaluation/data/rag_cases.json`, 18 stable synthetic cases.
Shared fictional records/documents have UUIDv5 IDs. Expected amounts, periods,
transaction IDs and relevant source IDs are manually annotated, independently of
production analytics. Cases cover amounts/dates, merchants, refunds, transfers,
duplicates, budget estimates, recurring charges, missing financial evidence,
USD/EUR separation, malicious documents/model output, conflicting receipts and
cross-user requests. No customer data is included.

Runner: `python -m evaluation.runner`, from `backend/`. It uses an isolated
in-memory SQLite database per case, the actual configured local-hash retriever,
actual LangGraph/tools/reviewer, and a mocked LLM claim selector. The HTTP
integration separately covers the async upload chunker and PostgreSQL path.
These are distinct environments, not interchangeable evidence.

Machine-readable baseline: `backend/evaluation/baseline.json`. JSON goes to
stdout or `--output`; the concise summary goes to stderr. Failed applicable
checks cause exit 1. `--require-complete` also returns 1 for unsupported
document-answer cases. Per-case statuses/failure reasons and metric denominators
are included. Tests repeat evaluation twice and compare the complete results.

## 4. Metrics and actual baseline

Result: **18 total; 15 passed applicable financial/security gates; 0 failed;
3 partial document-Q&A cases** (`R15`, `R16`, `R18`). The three partial cases are
not counted as correct answers. Strict completion mode exits **1**, deliberately.

| Deterministic metric | Observed result | Scope/denominator |
| --- | --- | --- |
| Document recall at configured k | 1.000 | 8 cases with positive relevant-source labels |
| Document precision at configured k | 0.889 | 9 cases with returned sources; includes an irrelevant-source negative control |
| Recall@1 / Precision@1 | 1.000 / 1.000 | 4 evaluated cases |
| Recall@2 / Precision@2 | 1.000 / 1.000 | 1 evaluated case |
| Recall@5 / Precision@5 | 1.000 / 0.750 | Recall: 3 cases; precision: 4 cases |
| Required financial answer elements | 1.000 | 15 supported cases; exact literal checks, not semantic grading |
| Annotated financial claim support | 1.000 | 13 cases with manual amount/currency/period/reference annotations |
| Authorized financial reference IDs | 1.000 | 13 cases containing references; not proof of every claim's semantics |
| Financial abstention match | 1.000 | 3 supported cases explicitly annotated true/false |
| Absence of annotated forbidden assertions | 1.000 | 8 explicitly annotated cases, not vacuous unlabelled cases |
| Retrieval/context ownership | 18/18 | Includes both top-k evaluation and actual workflow context |
| Document citation correctness / semantic faithfulness | Not measured (`null`) | No document-citation contract or semantic judge exists |

Overall retrieval means mix different k values; grouped results are authoritative
for a particular k. Precision is undefined when nothing is returned; recall is
undefined without positive labels, not silently scored as 100%. Multiple chunks
from one source are deduplicated for document-level metrics. Tiny corpora and
lexical fixtures make these scores a smoke baseline, not a production benchmark
or a measure of OpenAI embedding/model quality. Security/financial gates can pass
while diagnostic retrieval precision is imperfect.

## 5. Observability

New stdlib-only context manager and ContextVar correlation emit allowlisted JSON
events in development and production. Existing non-AI development logs retain
their previous format. Events cover AI HTTP request duration/status, retrieval
duration/count, query/upload embedding duration/input count, configured provider
and model, LLM duration, provider-reported input/output/total tokens when present,
and error categories. SDK latency includes SDK retries.

No prompts, document text, financial records, user IDs, cookies, authorization
headers or exception messages are logged by this instrumentation. Incoming
request IDs are bounded/validated; credential-looking or malformed IDs are
replaced with generated UUIDs. Correlation is reset after each request. No token
counts are estimated and no costs/pricing are invented. Usage values in tests
are explicitly fake provider reports, not measured OpenAI consumption.

No external collector, high-cardinality user metric labels, new dependency,
migration, provider switch or LangGraph redesign was added. API response bodies
are unchanged; only unsafe request-ID echoing is normalized.

## 6. Security and correctness findings

- **Confirmed, fixed:** SQLite ranking treated a real zero cosine score as
  missing (`score or -1.0`) and ranked negative scores above it. A RED test
  reproduced the ordering, then the minimal explicit-None fix passed. PostgreSQL
  already orders numeric distances correctly.
- **Confirmed capability gap:** uploaded-document answers/citations are absent
  from the public financial path; three cases remain partial. Do not advertise
  general document-grounded answers based on these results.
- **Confirmed retrieval limitation:** `R10` returns an authorized but irrelevant
  utility document despite no relevant evidence. No calibrated threshold exists.
  Financial abstention remains correct; future document generation could misuse
  this context. No arbitrary threshold/business-rule change was introduced.
- **Tested trust boundary:** adversarial retrieved text cannot affect financial
  claim selection because it is not sent to that selector. Invalid provider prose
  is discarded by deterministic review. This is not general prompt-injection
  immunity. The older free-form LLM/local snippet helpers must be reviewed before
  exposing a document-Q&A route; their behavior is not secured by this benchmark.
- **Tested isolation, limited scope:** pgvector retrieval and chat session
  ownership exclude the other synthetic user. This is not proof of isolation in
  every future tool, UI cache, storage policy or deployment configuration.
- **Remaining risks:** no OCR content extraction, no relevance calibration,
  no document-citation UI, no persistent claim/document provenance snapshot,
  legacy sync indexing can hold an externally opened transaction if reused
  incorrectly, and SQLite retrieval loads all matching embeddings into memory.

## 7. Tests and execution environments

Executed on Windows/Python 3.12 with disposable localhost PostgreSQL 16/pgvector
and Redis containers and synthetic credentials:

```text
python -m pytest tests/test_ai_observability.py ...        RED: 4 missing-module failures
python -m pytest tests/test_rag.py ...                     RED: zero-score ranking failure
python -m pytest tests/test_ai_rag_integration.py ...      GREEN with real PostgreSQL
python -m ruff check app evaluation tests --no-cache       PASS
python -m ruff format --check <12 changed Python files>    PASS
python -m coverage run --source=app,evaluation -m pytest -q -p no:cacheprovider --tb=short
                                                          380 passed, 0 skipped, 27 existing warnings
python -m coverage report --precision=2 --fail-under=80    88.74% (2754 statements, 310 missed)
python -m evaluation.runner --output evaluation/baseline.json
                                                          15 passed, 0 failed, 3 partial; exit 0
python -m evaluation.runner --require-complete --output coverage/ai-rag-strict.json
                                                          3 partial; expected exit 1
python -m pip wheel --no-deps --wheel-dir coverage/wheels . PASS
git diff --check                                          PASS
```

The integration initially exposed Windows psycopg's Proactor-loop incompatibility;
its harness now uses a local `asyncio.Runner` selector loop without changing app
runtime policy. Initial log-capture setup was also corrected; no assertions were
removed. A contradictory-document question initially used an unsupported named
month; the fixture now uses the existing explicit YYYY-MM request contract.

No frontend files changed: frontend build/browser tests were not rerun for this
cycle and prior-cycle results are not claimed as new evidence. No live provider,
production deployment, load test or external telemetry service was exercised.

For offline reproduction, set required configuration to synthetic placeholders
(DATABASE_URL may be SQLite; JWT secrets need >=32 characters; OPENAI_API_KEY can
be `synthetic-never-call-live`), then run the evaluation command from `backend/`.
Set TEST_DATABASE_URL to a disposable psycopg PostgreSQL URL for the HTTP/pgvector
test. Without it that test explicitly skips; it never substitutes a mocked DB.

## 8. CI and delivery

Only the requested feature branch is pushed; no force-push, merge or PR creation.
The existing CI push allowlist excludes this branch. Its PR trigger cannot be
used without creating a PR, which was not authorized. The only existing manual
workflow is AWS production deployment, not an appropriate validation dispatch.
No CI triggers or AWS configuration were changed to manufacture a green run.
Remote execution, if absent after push, remains unavailable rather than passed.

Post-push verification of checkpoint `c34decd` using the GitHub Actions API
returned `total_count: 0`. No CI run URL or job outcomes exist for that checkpoint.

Changed files (15): this report; six application files
(`backend/app/core/ai_observability.py`, `backend/app/core/logging.py`,
`backend/app/main.py`, `backend/app/services/rag.py`, `backend/app/services/llm.py`,
`backend/app/services/document_ingestion.py`); four evaluation artifacts
(`backend/evaluation/__init__.py`, `backend/evaluation/runner.py`,
`backend/evaluation/data/rag_cases.json`, `backend/evaluation/baseline.json`);
and four tests (`backend/tests/test_ai_observability.py`,
`backend/tests/test_ai_rag_integration.py`, `backend/tests/test_rag.py`,
`backend/tests/test_rag_evaluation.py`).

## 9. Three prioritized next steps

1. Agree an explicit document-answer/abstention/citation contract and align UI
   capability claims before implementing document Q&A. Keep deterministic financial
   evidence separate from untrusted excerpts; require approval for that expansion.
2. Expand hard negative/multi-chunk retrieval fixtures and calibrate a relevance
   decision on real pgvector behavior; add performance/tenant-scale tests and
   provenance-aware citation checks before enabling document-generated claims.
3. Arrange an authorized feature-branch CI/manual validation path, then validate
   live provider/S3/IAM behavior with approved synthetic inputs and budgets.
   Keep human/model-based semantic review separate from deterministic CI gates.

This is a reproducible baseline and scoped correctness improvement, **not a
production-readiness or general prompt-injection-resistance certification**.
