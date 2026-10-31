"""add investigation case state and append-only notes

Revision ID: 20261003_0005
Revises: 20260530_0004
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261003_0005"
down_revision: str | None = "20260530_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_cases",
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column(
            "assignee_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('new', 'needs_evidence', 'escalated', 'resolved')",
            name="ck_investigation_cases_status_known",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('escalate', 'request_verification', 'false_positive')",
            name="ck_investigation_cases_decision_known",
        ),
    )
    op.create_index(
        "ix_investigation_cases_assignee_user_id", "investigation_cases", ["assignee_user_id"]
    )
    op.execute(
        "INSERT INTO investigation_cases (transaction_id, status) "
        "SELECT id, 'new' FROM transactions"
    )

    op.create_table(
        "case_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("investigation_cases.transaction_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_case_notes_case_id", "case_notes", ["case_id"])
    op.create_index("ix_case_notes_author_id", "case_notes", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_case_notes_author_id", table_name="case_notes")
    op.drop_index("ix_case_notes_case_id", table_name="case_notes")
    op.drop_table("case_notes")
    op.drop_index("ix_investigation_cases_assignee_user_id", table_name="investigation_cases")
    op.drop_table("investigation_cases")
