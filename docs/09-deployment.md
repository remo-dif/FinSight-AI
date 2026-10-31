# 18. Deployment

## Local

Follow the [root README Quick Start](../README.md#quick-start): populate required
credentials first, build, start PostgreSQL/Redis, run the one-off Alembic upgrade,
then start backend/frontend. `docker compose up --build` alone neither supplies
secrets nor migrates an empty database. pgvector initialization is not schema creation.

`/readyz` checks database/Redis/storage availability, not migration revision or
provider health. Back up and review reused volume ownership before non-root rollout.

## Deployment status

The previous AWS account is closed. No AWS deployment or resource is currently asserted operational or verified. No account recovery, paid infrastructure, provisioning or deployment is authorized. AWS diagrams and the manual-only workflow remain historical/design portfolio evidence. Future hosting and its strict cost budget will be evaluated separately; no VPS deployment has been implemented.

## Historical / repository-supported AWS shape

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

## Portability boundary

The application runs as containers with PostgreSQL/pgvector and Redis; authentication and session-family correctness do not depend on AWS APIs. Future hosting must provide TLS termination, explicit trusted proxy CIDRs, durable evidence storage, secrets, backups/restore validation and appropriate database/Redis permissions. Current production configuration still requires the S3 storage backend; a future non-AWS storage policy or S3-compatible configuration must be evaluated explicitly, rather than assuming local ephemeral uploads are production-safe. No hosting-provider migration is implemented here.
