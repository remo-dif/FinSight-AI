# FinSight-AI

Production-grade SaaS portfolio project for an AI-assisted fraud investigation workspace.

## What Is Included

- FastAPI backend with SQLAlchemy 2, JWT auth, RBAC, audit logging, rate limiting, secure uploads, ingestion services, analytics tools, RAG retrieval, and hierarchical agent orchestration.
- Next.js 15 frontend with TypeScript, Tailwind, React Query, Zustand, accessible fraud-investigation workspace, AI copilot, evidence ingestion, and reusable UI primitives.
- PostgreSQL with pgvector support.
- Docker Compose for local full-stack development.
- GitHub Actions pipeline for backend/frontend linting, tests, production builds, Docker image builds, Trivy scans, GHCR publishing, and AWS ECS deployment.
- Architecture, UX, security, QA, deployment, and reviewer validation documents.

## Recent Updates

- Redesigned the first screen as an operational fraud-investigation workspace instead of a generic finance dashboard.
- Hardened the product direction around fraud analyst triage, evidence review, AI-grounded investigation, and auditable case decisions.
- Added compact case-review UI sections for operations overview, alert queue, risk drivers, entity graph, evidence timeline, case decisioning, analyst session, investigation copilot, and evidence ingestion.
- Updated Playwright end-to-end coverage to assert the redesigned workspace.
- Changed production frontend API routing to same-origin requests so deployed browsers call `/api/...` through the Application Load Balancer instead of `localhost:8000`.
- Configured AWS deployment primitives for ECS Fargate, RDS PostgreSQL, CloudWatch Logs, Secrets Manager, GitHub OIDC, and per-commit GHCR image deployment.

## Quick Start

```bash
docker compose up --build
```

Frontend: http://localhost:3000

Backend API: http://localhost:8000/docs

## Environment

Copy `.env.example` to `.env` and set the required secrets.

Production runtime secrets are stored in AWS Secrets Manager and injected into ECS task
definitions:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `JWT_REFRESH_SECRET_KEY`

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

## Monorepo Layout

```text
backend/          FastAPI API, services, agents, tests
frontend/         Next.js SaaS UI
docs/             Architecture, UX, security, QA, deployment docs
.github/          CI and AWS deployment workflows
docker-compose.yml
```
