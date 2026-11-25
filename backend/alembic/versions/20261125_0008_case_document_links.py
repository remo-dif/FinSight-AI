"""Link owner documents explicitly to investigation cases.

Revision ID: 20261125_0008
Revises: 20261031_0007
"""

import sqlalchemy as sa

from alembic import op

revision = "20261125_0008"
down_revision = "20261031_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_document_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("investigation_cases.transaction_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_file_id",
            sa.Uuid(),
            sa.ForeignKey("uploaded_files.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "linked_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "uploaded_file_id", name="uq_case_document_link"),
    )
    op.create_index("ix_case_document_links_case_id", "case_document_links", ["case_id"])
    op.create_index(
        "ix_case_document_links_uploaded_file_id", "case_document_links", ["uploaded_file_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_case_document_links_uploaded_file_id", table_name="case_document_links")
    op.drop_index("ix_case_document_links_case_id", table_name="case_document_links")
    op.drop_table("case_document_links")
