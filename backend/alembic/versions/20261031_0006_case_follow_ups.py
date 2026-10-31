"""Add append-only case follow-ups and monotonic concurrency revision.

Revision ID: 20261031_0006
Revises: 20261003_0005
"""

import sqlalchemy as sa

from alembic import op

revision = "20261031_0006"
down_revision = "20261003_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "investigation_cases",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "case_follow_ups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("investigation_cases.transaction_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("resulting_status", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "action", name="uq_case_follow_up_action"),
        sa.UniqueConstraint("case_id", "revision", name="uq_case_follow_up_revision"),
        sa.CheckConstraint(
            "action IN ('escalation_outcome', 'verification_outcome', 'close')",
            name="ck_case_follow_up_action",
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_case_follow_up_reason"),
        sa.CheckConstraint("revision > 0", name="ck_case_follow_up_revision"),
    )
    op.create_index("ix_case_follow_ups_case_id", "case_follow_ups", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_case_follow_ups_case_id", table_name="case_follow_ups")
    op.drop_table("case_follow_ups")
    op.drop_column("investigation_cases", "revision")
