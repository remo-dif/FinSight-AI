# FinSight-AI

Portfolio application for an AI-assisted fraud investigation workspace. Local and CI
checks provide evidence for individual features, not production readiness.

## What Is Included

- FastAPI backend with SQLAlchemy 2, JWT access tokens, rotating persisted refresh tokens, ownership checks, role dependencies, audit logging and Redis or development-memory rate limiting.
- Transaction analytics and investigation cases with explicit transition rules. CSV imports require explicit currencies; manual transaction creation still has a deferred USD-default risk.
- User-scoped uploads, PDF text extraction, embeddings and internal pgvector retrieval. Image files are validated, but OCR is not integrated.
- Next.js 15 frontend with TypeScript, Tailwind, React Query, Zustand, an investigation workspace, financial copilot, upload controls and reusable UI primitives. Some risk, graph and timeline panels remain illustrative UI, not implemented detection pipelines.
- PostgreSQL with pgvector support.
- Docker Compose for local full-stack development.
- GitHub Actions pipeline for backend/frontend linting, tests, production builds, Docker image builds, Trivy scans, GHCR publishing, and AWS ECS deployment.
- Architecture, UX, security, QA, deployment, and reviewer validation documents.

## Recent Updates

- Redesigned the first screen as an operational fraud-investigation workspace instead of a generic finance dashboard.
- Added auditable case decisions and deterministic financial-evidence review. The keyword router selects a financial specialist; the LLM selects allowed claim IDs rather than calling tools itself.
- Added compact case-review UI sections for operations overview, alert queue, risk drivers, entity graph, evidence timeline, case decisioning, analyst session, investigation copilot, and evidence ingestion.
- Updated Playwright end-to-end coverage to assert the redesigned workspace.
- Changed production frontend API routing to same-origin requests so deployed browsers call `/api/...` through the Application Load Balancer instead of `localhost:8000`.
- Configured AWS deployment primitives for ECS Fargate, RDS PostgreSQL, CloudWatch Logs, Secrets Manager, GitHub OIDC, and per-commit GHCR image deployment.

## Quick Start

Requirements: Docker Engine/Desktop with a current Compose v2 supporting
`env_file.required` and `up --wait`. Run commands from the repository root.

1. Copy `.env.example` to `.env` (`cp .env.example .env`, or
   `Copy-Item .env.example .env` in PowerShell). Do not commit `.env`.
2. Fill these values before starting containers:

   | Variable | Required local value |
   | --- | --- |
   | `POSTGRES_PASSWORD` | Your generated database password; use the same value in `DATABASE_URL`. |
   | `DATABASE_URL` | `postgresql+psycopg://finance:YOUR_PASSWORD@postgres:5432/finance_ai`. URL-encode reserved password characters. |
   | `REDIS_PASSWORD` | At least 32 URL-safe letters, digits, `_` or `-`; use the same value in `REDIS_URL`. |
   | `REDIS_URL` | `redis://:YOUR_REDIS_PASSWORD@redis:6379/0`. |
   | `JWT_SECRET_KEY`, `JWT_REFRESH_SECRET_KEY` | Two different random secrets, each at least 32 characters. |
   | `OPENAI_API_KEY` | Required by current configuration, including with local embeddings; a valid provider key is needed for remote AI calls. |

   Generate independent random values locally, for example with
   `python -c "import secrets; print(secrets.token_hex(32))"` or
   `openssl rand -hex 32`. Hex passwords avoid URL-encoding ambiguity. Replace every
   `REPLACE-...` marker; example markers are not usable credentials.
3. Keep `APP_ENV=development` and `STORAGE_BACKEND=local` for this local setup.
   Compose explicitly uses Redis even if `.env` says `RATE_LIMIT_BACKEND=memory`.
   `EMBEDDING_BACKEND=local` selects deterministic development hash vectors, not a
   semantic model or an automatic fallback. Remote embedding failures never switch models.

Build, start the dependencies, run migrations once, then start the application:

```bash
docker compose config --quiet
docker compose build
docker compose up -d --wait postgres redis
docker compose run --rm --no-deps backend python -m alembic upgrade head
docker compose up -d --wait backend frontend
```

Frontend: http://localhost:3000. Backend OpenAPI UI (development):
http://localhost:8000/docs. The Compose browser build uses
`NEXT_PUBLIC_API_URL=http://localhost:8000`; frontend server reads use
`API_INTERNAL_URL=http://backend:8000`. PostgreSQL/Redis ports are not published.

`/health` is liveness. `/readyz` checks a database connection, configured Redis and
storage access; it does not verify migrations, OpenAI availability or AI quality.
The PostgreSQL initialization script enables pgvector only. Neither Compose nor
the backend startup command runs Alembic automatically. Run migrations before using
authenticated APIs, and again after updating to a schema-changing release.

Existing databases keep their original password when their volume is reused;
editing `.env` does not rotate database credentials. Reused root-owned upload
volumes may need a separately reviewed UID/GID 10001 permission migration: see
[the storage follow-up](docs/24-security-integration-follow-up.md). Back up data;
do not delete volumes to resolve an ownership or credential mismatch.

For non-AI development checks only, an explicit non-secret placeholder key of at
least ten characters satisfies configuration validation. It is not an offline mode:
chat still attempts provider calls, and remote embeddings fail if the key is invalid.
Do not use placeholders as production secrets or treat a deterministic fallback as
evidence that a provider integration was validated.

## Public API and AI Boundaries

| Capability | Current behavior |
| --- | --- |
| Authentication | JSON register/login, refresh/logout and `/api/auth/me`; protected APIs use `Authorization: Bearer <access_token>`. Obtain a token through JSON login before using Swagger's Bearer authorization. |
| Passwords | Registration requires at least 10 characters; registration/login accept at most 72 UTF-8 bytes. No truncation or normalization. Shorter legacy login passwords remain accepted. No public password-change/reset endpoint exists. |
| Cases | List/detail, audited state/assignment/decision updates and append-only notes. Decisions pin status; generic reopening/resolution after a decision is intentionally restricted. |
| Transactions | User-scoped list/create, monthly summaries and spending comparisons; currencies remain isolated. |
| Uploads | CSV transactions; embedded PDF text extraction and chunk indexing. Images currently produce metadata placeholders, not extracted OCR text. |
| Chat | Six keyword-routed financial intents, canonical transaction evidence and deterministic review/fallback. Responses expose transaction references in tool results. |
| Document Q&A | Not user-accessible: retrieval runs internally, but the public financial answer path does not use retrieved documents to ground its answer. Document citations and minimum relevance thresholds are not implemented. |
| Evaluation/observability | Internal synthetic evaluation harness and allowlisted structured AI-operation logs. These are not a public document-Q&A endpoint or full OpenTelemetry tracing. |

CSV imports use `date` (or `Date`), not the JSON transaction field `posted_at`.
For example, an explicit-currency CSV can contain:

```csv
date,merchant,amount,currency
2026-10-20,Example merchant,-12.50,EUR
```

Amounts are required and finite; numeric zero is valid. With no import-level
currency selected, each row needs a supported explicit currency and mixed currencies
are preserved. The CSV-only selector can instead supply an explicit `import_currency`;
conflicting row currencies reject the whole import. No conversion or implicit currency
assignment is performed by CSV imports.

See [the consistency report](docs/25-api-docs-configuration-consistency.md) for the
capability matrix, validation evidence and remaining limitations.

## Rate Limits and API Errors

The general default is 20 attempts per client IP per minute; POST `/api/auth/login`
has an additional default budget of 10. Successes, failed credentials and malformed
requests count. A request rejected by the login-specific limit can still consume
available general quota. Requests rejected because that quota is already exhausted
do not increment its counter or extend its expiry. Both backends report the general
limit and remaining count on admitted responses. Memory uses a process-local sliding
window; Redis uses fixed minute windows and expiring keys. Redis failures return 503
(`Retry-After: 1`), with no memory fallback. Exhausted quotas return 429
(`Retry-After: 60`). Limits are per IP, not account lockouts; shared NATs share
budgets. Production requires Redis.

Validation failures return 422; malformed CSV data returns controlled 400 errors.
Auth validation keeps error locations/messages/types but omits submitted input to
avoid echoing passwords or refresh tokens. Registration's existing-email 409 remains
an explicit enumeration tradeoff. Trusted proxy CIDRs must reflect real ingress:
see [the proxy contract](docs/23-proxy-auth-container-hardening.md).

## Environment

Copy `.env.example` to `.env` and set the required secrets.

Production runtime secrets are stored in AWS Secrets Manager and injected into ECS task
definitions:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `JWT_REFRESH_SECRET_KEY`
- `REDIS_URL` when it contains credentials

Non-secret production settings are configured on ECS task definitions or GitHub Actions
variables, depending on whether the value is runtime app configuration or deployment
configuration.

## Production Deployment

See [`AWS-TECHNOLOGIES.md`](AWS-TECHNOLOGIES.md) for a concise inventory and architecture diagram of the AWS services currently in use.

The AWS target is ECS on Fargate behind CloudFront and an Application Load Balancer. Resource names
and endpoints are held in the protected GitHub `production` environment rather than committed.
Production deployment is blocked unless CloudFront-to-ALB traffic is HTTPS-only, the distribution
has WAF attached, RDS is private/encrypted/Multi-AZ, and the private uploads bucket is encrypted.

CI publishes immutable images tagged by commit SHA:

- `ghcr.io/remo-dif/finsight-ai-backend:<commit-sha>`
- `ghcr.io/remo-dif/finsight-ai-frontend:<commit-sha>`

The `deploy-aws` workflow can deploy a specific commit SHA manually and is configured to
deploy successful `master` commits when `AWS_DEPLOY_ENABLED=true`.

## CI Triggers and Local Checks

CI runs on pushes to `main`/`master` and on pull-request events. A push to a feature,
fix or chore branch alone does not start CI. All existing backend, frontend and
container checks remain in place; dependency review runs for pull requests. Images
are published only for successful `master` push runs, not PRs or `main` pushes.
Deployment has its own protected-environment/configuration gates; see
[AWS CI/CD](docs/15-aws-cicd.md). A green CI result does not authorize deployment.

Backend: install `backend/.[dev]` with `backend/constraints-security.txt`, set the
required application environment and run `ruff check .` and `pytest` from `backend`.
`TEST_DATABASE_URL` and `TEST_REDIS_URL` must point to disposable test services:
the migration smoke upgrades/downgrades its database. Unconfigured integrations
skip; SQLite/mocks are not evidence of PostgreSQL/Redis validation.

Frontend, from `frontend`: `npm ci`, `npm run lint`, `npm run typecheck`,
`npm run build`, `npx playwright install --with-deps`, then `npm run test:e2e`.
The browser suite uses API fixtures; real backend integration is tested separately.
Do not interpret demo workspace records as production fraud evidence.

## Monorepo Layout

```text
backend/          FastAPI API, services, agents, tests
frontend/         Next.js SaaS UI
docs/             Architecture, UX, security, QA, deployment docs
.github/          CI and AWS deployment workflows
docker-compose.yml
```
