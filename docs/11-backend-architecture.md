# 7. Backend Architecture

## Stack

- FastAPI
- Python 3.12
- SQLAlchemy 2
- PostgreSQL
- Alembic-ready schema layout
- OpenAI SDK and LangGraph boundary

## Layers

- API routes handle transport and dependencies.
- Repositories own database queries.
- Services own business logic: ingestion, analytics, categorization, RAG, audit.
- Agents own orchestration and AI response review.
- Security utilities own JWT, bcrypt, and RBAC dependencies.

## Tradeoffs

The current implementation keeps background ingestion synchronous for simplicity. Production should move OCR, embeddings, and large CSV imports to workers with retry and idempotency controls.
