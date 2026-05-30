"""move embeddings to pgvector with chunk metadata

Revision ID: 20260530_0004
Revises: 20260530_0003
Create Date: 2026-05-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260530_0004"
down_revision: str | None = "20260530_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "embeddings",
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("embeddings", sa.Column("chunk_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "embeddings",
        sa.Column(
            "embedding_model",
            sa.String(length=120),
            nullable=False,
            server_default="legacy-placeholder",
        ),
    )
    op.add_column(
        "embeddings",
        sa.Column(
            "embedding_dimensions",
            sa.Integer(),
            nullable=False,
            server_default=str(EMBEDDING_DIMENSIONS),
        ),
    )
    op.add_column(
        "embeddings",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute("UPDATE embeddings SET chunk_hash = md5(chunk_text) WHERE chunk_hash IS NULL")
    op.alter_column("embeddings", "chunk_hash", nullable=False)

    op.alter_column(
        "embeddings",
        "embedding",
        new_column_name="embedding_legacy",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.execute(f"ALTER TABLE embeddings ADD COLUMN embedding vector({EMBEDDING_DIMENSIONS})")
    zero_vector = "[" + ",".join("0" for _ in range(EMBEDDING_DIMENSIONS)) + "]"
    op.get_bind().execute(sa.text("UPDATE embeddings SET embedding = :embedding"), {"embedding": zero_vector})
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding SET NOT NULL")

    op.create_index(
        "ix_embeddings_user_source_chunk_hash",
        "embeddings",
        ["user_id", "source_type", "source_id", "chunk_hash"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_embedding_hnsw "
        "ON embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    op.alter_column("embeddings", "chunk_index", server_default=None)
    op.alter_column("embeddings", "embedding_model", server_default=None)
    op.alter_column("embeddings", "embedding_dimensions", server_default=None)
    op.alter_column("embeddings", "metadata_json", server_default=None)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_embedding_hnsw")
    op.drop_index("ix_embeddings_user_source_chunk_hash", table_name="embeddings")
    op.drop_column("embeddings", "embedding")
    op.alter_column(
        "embeddings",
        "embedding_legacy",
        new_column_name="embedding",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.drop_column("embeddings", "metadata_json")
    op.drop_column("embeddings", "embedding_dimensions")
    op.drop_column("embeddings", "embedding_model")
    op.drop_column("embeddings", "chunk_hash")
    op.drop_column("embeddings", "chunk_index")
