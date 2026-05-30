# 18. Deployment

## Local

`docker compose up --build`

## Production Shape

- Frontend: Vercel, Azure Static Web Apps, or container hosting.
- Backend: container app platform with autoscaling.
- Database: managed PostgreSQL with pgvector.
- Object storage: private bucket/container for uploads.
- Secrets: managed secret vault.
- Observability: OpenTelemetry traces, metrics, structured logs, alerts.

## Release Checklist

- Run database migrations.
- Verify secrets and CORS origins.
- Run CI checks.
- Run smoke tests against `/health`.
- Verify upload and chat flows with non-sensitive sample data.
