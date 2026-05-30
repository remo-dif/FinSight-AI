# 8. Database Design

## Tables

- `users`: identity, role, password hash, active state.
- `transactions`: normalized financial rows.
- `uploaded_files`: secure upload metadata and processing status.
- `chat_sessions`: user conversation containers.
- `chat_messages`: persisted chat messages.
- `budgets`: monthly budget limits by category.
- `embeddings`: personal knowledge-base chunks and vector placeholder.
- `audit_logs`: security and AI-tool audit trail.

## pgvector

The Docker database enables `vector`. The current ORM stores embedding payloads behind a service boundary so the column can be migrated to a native vector type when production migrations are introduced.

## Indexing

User-owned tables index `user_id`. Transactions also index posted date, merchant, and category because those fields drive dashboard and tool queries.
