# Personal Finance AI Assistant

Production-grade SaaS portfolio project for a multimodal AI personal finance assistant.

## What Is Included

- FastAPI backend with SQLAlchemy 2, JWT auth, RBAC, audit logging, rate limiting, secure uploads, ingestion services, analytics tools, RAG retrieval, and hierarchical agent orchestration.
- Next.js 15 frontend with TypeScript, Tailwind, React Query, Zustand, accessible dashboard, AI chat, upload flow, and reusable UI primitives.
- PostgreSQL with pgvector support.
- Docker Compose for local full-stack development.
- GitHub Actions pipeline for linting, tests, build, and security scan placeholders.
- Architecture, UX, security, QA, deployment, and reviewer validation documents.

## Quick Start

```bash
docker compose up --build
```

Frontend: http://localhost:3000

Backend API: http://localhost:8000/docs

## Environment

Copy `.env.example` to `.env` and set the required secrets.

## Monorepo Layout

```text
backend/          FastAPI API, services, agents, tests
frontend/         Next.js SaaS UI
docs/             Architecture, UX, security, QA, deployment docs
.github/          CI pipeline
docker-compose.yml
```
