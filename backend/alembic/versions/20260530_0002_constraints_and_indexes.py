"""add production constraints and indexes

Revision ID: 20260530_0002
Revises: 20260530_0001
Create Date: 2026-05-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260530_0002"
down_revision: str | None = "20260530_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint("ck_transactions_currency_len", "transactions", "char_length(currency) = 3")
    op.create_check_constraint("ck_transactions_source_known", "transactions", "source IN ('manual', 'csv')")
    op.create_check_constraint(
        "ck_uploaded_files_status_known",
        "uploaded_files",
        "status IN ('uploaded', 'stored', 'processed', 'indexed', 'failed')",
    )
    op.create_check_constraint("ck_chat_messages_role_known", "chat_messages", "role IN ('user', 'assistant', 'system')")
    op.create_check_constraint("ck_budgets_month_format", "budgets", "month ~ '^[0-9]{4}-[0-9]{2}$'")
    op.create_check_constraint("ck_budgets_limit_positive", "budgets", "limit_amount >= 0")
    op.create_unique_constraint("uq_budgets_user_month_category", "budgets", ["user_id", "month", "category"])
    op.create_index("ix_transactions_user_posted_at", "transactions", ["user_id", "posted_at"])
    op.create_index("ix_transactions_user_category_posted_at", "transactions", ["user_id", "category", "posted_at"])
    op.create_index("ix_chat_messages_session_created_at", "chat_messages", ["session_id", "created_at"])
    op.create_index("ix_embeddings_user_source", "embeddings", ["user_id", "source_type", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_embeddings_user_source", table_name="embeddings")
    op.drop_index("ix_chat_messages_session_created_at", table_name="chat_messages")
    op.drop_index("ix_transactions_user_category_posted_at", table_name="transactions")
    op.drop_index("ix_transactions_user_posted_at", table_name="transactions")
    op.drop_constraint("uq_budgets_user_month_category", "budgets", type_="unique")
    op.drop_constraint("ck_budgets_limit_positive", "budgets", type_="check")
    op.drop_constraint("ck_budgets_month_format", "budgets", type_="check")
    op.drop_constraint("ck_chat_messages_role_known", "chat_messages", type_="check")
    op.drop_constraint("ck_uploaded_files_status_known", "uploaded_files", type_="check")
    op.drop_constraint("ck_transactions_source_known", "transactions", type_="check")
    op.drop_constraint("ck_transactions_currency_len", "transactions", type_="check")
