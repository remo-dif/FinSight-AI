# 15. DevOps Layer

## Local Services

- `frontend`: Next.js application on port 3000.
- `backend`: FastAPI application on port 8000.
- `postgres`: PostgreSQL 16 with pgvector on port 5432.

## Containers

The backend image installs Python dependencies and OCR runtime support. The frontend image builds a production Next.js bundle. Docker Compose wires service dependencies and persistent volumes.

## Observability Roadmap

- JSON structured logs.
- Request correlation IDs.
- OpenTelemetry tracing.
- API latency, upload processing, AI tool call, and database metrics.
- Alerting for auth failures, upload failures, and anomalous API error rates.
