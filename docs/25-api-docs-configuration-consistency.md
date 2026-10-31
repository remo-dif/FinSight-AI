# API, Configuration and Documentation Consistency

Audit date: 2026-10-31

Branch: `chore/api-docs-consistency`
Baseline: clean branch at the fetched `origin/master` commit after PR #6 was verified merged.

## 1. Findings

- The README already linked to this report, but the report file did not exist. This change
  supplies the missing document.
- Redis and in-memory rate limiting enforced the same admission limits, but Redis incremented
  counters even for requests already rejected at that quota, while memory did not. Successful
  admitted responses also exposed `X-RateLimit-Limit` and `X-RateLimit-Remaining` only when Redis
  was selected. Both behaviors are now aligned and covered by tests.
- Password request models and bcrypt helpers already enforce an explicit 72 UTF-8-byte limit.
  Existing tests cover exact byte boundaries, multibyte values, normalization behavior and
  register/login round trips. No password implementation change was needed.
- The README's local setup, API capability statements and CI trigger summary agree with the
  inspected implementation. Compose, environment examples, initialization and readiness behavior
  are summarized below.
- No workflow, password-hashing, database-schema or AI/RAG implementation changes were needed.
  This report distinguishes verified behavior from internal infrastructure and deferred features.

## 2. Changed files and rationale

- `README.md`: documents that already-exhausted quotas are not incremented or extended, and that
  both limiter implementations return the same general-quota headers for admitted requests.
- `backend/app/core/rate_limit.py`: makes Redis admission atomic per quota without incrementing
  over-limit counters; adds the existing Redis general-quota headers to admitted memory responses.
- `backend/tests/test_rate_limit.py`: updates the Redis test double to model non-incrementing
  rejections and tests the Redis response headers.
- `backend/tests/test_rate_limit_accounting.py`: tests header parity and verifies real Redis
  counters remain capped during concurrent rejected requests.
- `docs/25-api-docs-configuration-consistency.md`: records the audit, compatibility contract,
  capabilities and actual validation results.

## 3. API and configuration compatibility

### Public API

The backend mounts authentication (`/api/auth/...`), transactions (`/api/transactions/...`),
cases (`/api/cases/...`), uploads (`/api/uploads`) and chat (`POST /api/chat`). `/health` is
liveness; `/readyz` checks database connectivity, configured Redis and local/S3 storage access.
Readiness does not check schema migration state, OpenAI availability or answer quality.

### Local Quick Start

The README instructions match the current Compose and backend configuration:

- Compose v2 must support `env_file.required` and `up --wait`.
- `.env.example` contains no usable secrets. Local setup requires generated, distinct JWT secrets
  (at least 32 characters), a PostgreSQL password matching `DATABASE_URL`, a Redis password and
  matching `REDIS_URL`, and an `OPENAI_API_KEY` of at least 10 characters.
- Compose uses authenticated PostgreSQL and Redis, does not publish their ports, and explicitly
  selects Redis rate limiting even though the example's direct-run default is memory.
- Local storage and development mode are appropriate for the documented local setup.
  `EMBEDDING_BACKEND=local` selects deterministic hash embeddings; it is not an offline mode and
  does not prevent remote chat calls.
- PostgreSQL initialization only enables pgvector. Neither Compose nor the backend startup runs
  Alembic. The documented explicit `alembic upgrade head` step is required before authenticated
  use. The backend health check targets `/readyz`.
- The local browser API URL is `http://localhost:8000`; frontend server-side API calls use
  `http://backend:8000`. Production frontend requests default to same-origin `/api` paths.
- Existing PostgreSQL volumes retain their initialized credentials. The README correctly warns
  that changing `.env` does not rotate them and that old upload-volume ownership may need a
  separately reviewed migration.

Production settings reject SQLite, require S3 storage and Redis rate limiting, and require explicit
CORS origins. Secret placeholders in local setup are not production defaults.

### Password policy

The registration contract is at least 10 Unicode characters and no more than 72 UTF-8 bytes.
Login uses the same byte ceiling but imposes no minimum, preserving shorter existing passwords.
Passwords are neither normalized nor silently truncated. `verify_password` also rejects inputs
over 72 bytes, and the bcrypt algorithm and existing hashes are unchanged. Existing hashes created
from passwords within this limit remain compatible. A legacy password longer than 72 bytes cannot
be safely accepted under this policy; if an older bcrypt version truncated such an input, that
account may require a separately designed recovery path. There is no public password-change/reset
endpoint.

## 4. Rate limiter behavior and limitations

- General quota defaults to 20 requests per client IP per minute; `POST /api/auth/login` has an
  additional quota of 10. Successful login, failed credentials and malformed login requests are
  charged before endpoint validation. Limits are per IP, not per account.
- When a request is admitted by the general quota, both middleware backends report the general
  limit and remaining count in `X-RateLimit-Limit` and `X-RateLimit-Remaining`.
- A request rejected by the login-specific quota may already have consumed general quota.
  A request rejected because a particular quota is already exhausted does not increment that
  quota or extend its expiry. Redis performs this check/increment atomically for each quota key.
- Memory uses a process-local sliding 60-second window. Redis uses expiring fixed-minute keys.
  These window shapes differ intentionally; fixed windows can admit a burst near a minute
  boundary. Memory counters are not shared across worker processes, so production requires Redis.
- Quota exhaustion returns HTTP 429 with `{"detail":"Rate limit exceeded"}` and
  `Retry-After: 60`. Redis storage failures fail closed with HTTP 503,
  `{"detail":"Rate-limit service unavailable"}` and `Retry-After: 1`; there is no memory fallback.
- General and login counters are separate Redis script invocations. If Redis fails after the
  general counter was charged but before the login counter is checked, the request fails closed
  with 503 and the general charge remains until expiry. This is bounded by the short key TTL and
  does not permit authentication to bypass the limiter.

## 5. CI trigger behavior

`[ci.yml](../.github/workflows/ci.yml)` runs on pushes to `main` or `master` and on all
pull-request events; it has no pull-request branch filter. A push to a feature/fix/chore branch
alone does not run CI. Backend lint, migration smoke and tests; frontend audit, lint, typecheck,
build and end-to-end tests; and container build/scan jobs remain configured. The container job
publishes immutable SHA-tagged images only for successful `master` push runs. Dependency review
is pull-request-only.

`[deploy-aws.yml](../.github/workflows/deploy-aws.yml)` supports a successful `master` CI
`workflow_run` and manual `workflow_dispatch` with an image SHA. Both require
`AWS_DEPLOY_ENABLED=true` and the protected production environment/configuration. The deployment
workflow was inspected but not run. No workflow changes were necessary.

## 6. AI/RAG capability matrix

| Capability | Verified status |
| --- | --- |
| Financial chat | User-accessible. The UI asks about summaries, category spending, merchants, unusual transactions, recurring charges and estimated budgets. The backend routes six intent families to transaction-backed tools and applies deterministic financial review. |
| Transaction evidence references | Returned in financial tool results. These are transaction references, not document citations. |
| PDF/CSV ingestion | User-accessible. CSVs import transactions; text-based PDFs are extracted and indexed. |
| pgvector retrieval | Internal infrastructure. Chat invokes retrieval, but every current public specialist tool result includes `_evidence`; the answer path selects supported financial claim IDs and the reviewer renders those facts. The retrieved excerpts are not used to ground the current public financial answer. |
| Document-grounded Q&A | Not currently user-accessible. There is no public document-Q&A route or active public answer path grounded in retrieved excerpts. |
| Retrieved-document citations | Not implemented/exposed. No document citation contract appears in the public chat response. |
| Minimum relevance threshold | Not implemented. Retrieval ranks a bounded set of results; no minimum score cutoff is enforced. |
| OCR | Not integrated into ingestion. Image uploads are validated and represented by metadata placeholders; scanned PDFs with no extractable text can require OCR. The container includes the Tesseract executable, but the ingestion path does not invoke it. |
| Evaluation/observability | Internal utilities. The synthetic evaluation runner reports 18 cases: 15 passed, 0 failed and 3 partial for unsupported answer capability. Semantic faithfulness and document-citation correctness are unset, not measured. Structured AI-operation telemetry is not equivalent to full OpenTelemetry tracing. |

Accordingly, document Q&A, retrieved-document citations, a relevance threshold and OCR remain
deferred. No RAG feature was added in this audit.

## 7. Test commands and actual results

Validation used an isolated backend virtual environment and disposable local PostgreSQL/pgvector
and Redis containers bound only to loopback. Test credentials were synthetic and were not written
to repository files. The backend integration suite uses deterministic mocked OpenAI SDK calls;
provider quality or live OpenAI connectivity was not validated.

| Check | Result |
| --- | --- |
| Focused auth/password/rate-limit/security regression tests, with Redis configured | **PASS** — 94 passed, 0 failed, 0 skipped. |
| Full backend suite with `TEST_DATABASE_URL` and `TEST_REDIS_URL` configured | **PASS** — 565 passed, 0 failed, 0 skipped; 161 deprecation warnings. |
| `ruff check .` from `backend` | **PASS** — all checks passed. |
| Ruff format check on the three changed Python files | **PASS**. |
| Repository-wide `ruff format --check .` | **FAIL (pre-existing scope)** — 18 files would be reformatted; 79 were already formatted. The unrelated files were left untouched. |
| `npm run lint` from `frontend` | **PASS**. |
| `npm run typecheck` from `frontend` | **PASS**. |
| `npm run build` from `frontend` | **PASS**. |
| `docker compose config --quiet` with synthetic local values | **PASS**. |
| Docker Compose backend/frontend image build; backend rebuilt after limiter changes | **PASS**. |
| Internal `python -m evaluation.runner` | **15 passed, 0 failed, 3 partial**; partial means unsupported answer capability, not a fully implemented document-Q&A pass. |
| GitHub Actions static lint (`actionlint`) | **NOT RUN** — `actionlint` is unavailable in the environment. Workflow triggers and jobs were checked against the YAML directly. |
| Browser end-to-end suite | **NOT RUN** — no user-facing frontend behavior changed. |

The full backend run emitted SQLAlchemy `Result.tuples()` deprecation warnings and the
pytest-asyncio unset fixture-loop-scope warning. They did not fail tests. PostgreSQL and Redis
integration tests ran against the disposable services rather than mocks.

## 8. Remaining risks and deferred work

- Document-grounded Q&A, source citations, relevance filtering and OCR remain unimplemented.
- The three partial synthetic evaluation cases remain capability gaps; no semantic faithfulness or
  document-citation correctness score is available.
- Existing bcrypt hashes remain supported without migration for passwords within the policy.
  Recovery for passwords that may previously have exceeded bcrypt's 72-byte input limit is not
  addressed.
- The in-memory limiter is process-local and sliding-window; it is for development/testing only.
  Redis uses fixed windows, and its two quota keys are not updated in one cross-key transaction.
- The repository-wide Ruff format failure predates and is unrelated to these focused changes.
- Live AWS proxy settings, production secrets, deployment behavior and provider quality were not
  validated. No production service was accessed or changed.
