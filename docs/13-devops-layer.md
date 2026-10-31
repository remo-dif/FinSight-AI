# 15. DevOps Layer

## Local Services

- `frontend`: Next.js application on port 3000.
- `backend`: FastAPI application on port 8000.
- `postgres`: PostgreSQL 16 with pgvector on internal port 5432; not published to the host by Compose.
- `redis`: authenticated Redis on internal port 6379 for shared rate limiting; not published to the host by Compose.

## Containers

The backend image installs Python dependencies and the Tesseract binary, but application ingestion does not call OCR. The frontend image builds a production Next.js bundle. Both applications run as UID/GID 10001; Compose wires service dependencies and persistent volumes. Existing root-owned upload volumes need an explicitly reviewed permission migration before reuse.

## Implemented Observability

- JSON structured logs and request correlation IDs.
- Allowlisted AI-operation metadata: duration, outcome/error category, retrieval/chunk counts and available provider token usage.
- No logging of raw prompts, document contents, transaction data or provider exception text through the AI-operation logger.

## Observability Roadmap

- OpenTelemetry tracing.
- Exported API/database metrics, dashboards and automated quality/cost monitoring.
- Alerting for auth failures, upload failures, and anomalous API error rates.
