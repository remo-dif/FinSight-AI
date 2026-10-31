# 7. Backend Architecture

## Stack

- FastAPI
- Python 3.12
- SQLAlchemy 2
- PostgreSQL
- Alembic migrations for the current schema
- OpenAI SDK and LangGraph boundary

## Layers

- API routes handle transport and dependencies.
- Repositories own database queries.
- Services own business logic: ingestion, analytics, categorization, RAG, audit.
- Agents own orchestration and AI response review.
- Security utilities own JWT, bcrypt and role-check helpers. Uploads enforce USER/ADMIN roles; case, transaction and chat routes enforce active-user authentication and ownership, not a separate analyst-role policy.

## Tradeoffs

The async upload endpoint awaits extraction, embedding generation and persistence within the request lifecycle. Blocking extraction is offloaded to threads and provider calls complete before opening the persistence transaction. This is request-bound ingestion, not a background worker queue. Queued jobs with retry/idempotency controls and real OCR remain planned.

The public AI endpoint is financial chat through application-selected tools. Internal RAG indexing/retrieval exists, but document Q&A, document citations and configurable minimum retrieval-score thresholds are not exposed public capabilities.
