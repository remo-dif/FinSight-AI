# 16. Testing Strategy

## Backend

- Unit tests for analytics tools, security helpers, ingestion validators, and agent routing.
- Integration tests for API routes using test database fixtures.
- Contract tests for frontend API clients.

## Frontend

- Component tests for cards, upload controls, chat interactions, and dashboard states.
- Playwright E2E for upload, dashboard load, and assistant question flow.

## AI

- Golden tests for tool-only plans.
- Reviewer tests for unsupported claims and prompt injection attempts.
- Regression dataset for categorization and anomaly detection.

## CI Gates

- Backend lint and pytest.
- Frontend lint, typecheck, test, and build.
- Dependency and container security scans.
