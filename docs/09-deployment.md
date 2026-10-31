# 18. Deployment

## Local

Follow the [root README Quick Start](../README.md#quick-start): populate required
credentials first, build, start PostgreSQL/Redis, run the one-off Alembic upgrade,
then start backend/frontend. `docker compose up --build` alone neither supplies
secrets nor migrates an empty database. pgvector initialization is not schema creation.

`/readyz` checks database/Redis/storage availability, not migration revision or
provider health. Back up and review reused volume ownership before non-root rollout.

## Production Shape

- Configured deployment target: ECS Fargate frontend/backend behind CloudFront/ALB.
- Managed PostgreSQL/pgvector, Redis and private S3 uploads; Secrets Manager and GitHub OIDC.
- Implemented application observability: structured operation logs and request correlation.
  Full OpenTelemetry tracing/operational alerting requires separate integration/verification.
- See [AWS CI/CD](15-aws-cicd.md). Repository configuration describes intended gates;
  it does not prove that the live AWS topology satisfies them.

## Release Checklist

- Run database migrations.
- Verify secrets and CORS origins.
- Run CI checks.
- Run smoke tests against `/readyz` for backend readiness and `/` for the frontend.
- Verify upload and chat flows with non-sensitive sample data.
