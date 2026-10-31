# 16. Testing Strategy

## Backend

- Unit tests for analytics tools, security helpers, ingestion validators, and agent routing.
- Integration tests for API routes using test database fixtures.
- Password/OpenAPI and validation-error regressions, limiter accounting tests, and PostgreSQL case-concurrency/HTTP tests.
- PostgreSQL/Redis integrations require disposable `TEST_DATABASE_URL` / `TEST_REDIS_URL`; unconfigured tests skip rather than substitute mocks.

## Frontend

- Playwright browser tests for dashboard, auth/error handling, case workflow, uploads, chat and CSP, across configured desktop/mobile profiles.
- Browser API responses are fixtures; real backend/provider integration has separate tests. There is no separate component-unit test runner in the current package scripts.

## AI

- Keyword routing, graph execution and deterministic financial claim/reviewer tests with controlled model outputs.
- Reviewer tests for unsupported claims and prompt injection attempts.
- Regression dataset for categorization and anomaly detection.
- Internal AI/RAG evaluation with synthetic data and explicit partial results for unsupported document Q&A/citations. It does not establish live-model quality or production document grounding.

## CI Gates

- Backend lint and pytest.
- Frontend lint, typecheck, test, and build.
- Dependency and container security scans.

CI runs on pushes to `main`/`master` and pull requests. Feature-branch pushes alone
do not run it. Dependency review executes on PRs; image publication requires a master
push. No checks are removed or downgraded for a documentation-only change. Record
new commands/results separately from earlier cycle reports; skipped checks are not PASS.
