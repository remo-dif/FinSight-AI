# 8. Database Design

## Tables

- `users`: identity, role, password hash, active state.
- `transactions`: normalized financial rows.
- `uploaded_files`: secure upload metadata and processing status.
- `chat_sessions`: user conversation containers.
- `chat_messages`: persisted chat messages.
- `budgets`: monthly budget limits by category.
- `embeddings`: user-scoped text chunks, source metadata, embedding model/dimensions and vectors.
- `audit_logs`: security and AI-tool audit trail.
- `investigation_cases`, `case_notes`: transaction-keyed investigation state and append-only notes; a separate case-ID migration remains deferred.

## pgvector

The Docker database enables `vector`. `EmbeddingVector` uses native `vector(1536)` on PostgreSQL and JSON on SQLite. Migration `20260530_0004_pgvector_embeddings` already introduces the native column, chunk metadata and an HNSW cosine index; this is not a future vector migration.

Retrieval filters by user, embedding model and dimensions, then ranks by cosine distance. It returns top-K results without a minimum relevance threshold. The vectors and source metadata support internal retrieval; their presence does not establish document-Q&A or public citation support.

## Indexing

User-owned tables index `user_id`. Transactions also index posted date, merchant, and category because those fields drive dashboard and tool queries.
