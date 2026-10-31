"""Persist independent refresh families without changing existing token material.

Revision ID: 20261031_0007
Revises: 20261031_0006
"""

import sqlalchemy as sa

from alembic import op

revision = "20261031_0007"
down_revision = "20261031_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_token_families",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_refresh_token_families_user_id", "refresh_token_families", ["user_id"])
    op.add_column("refresh_tokens", sa.Column("family_id", sa.Uuid(), nullable=True))
    # UNION (not UNION ALL) bounds recursion even for malformed historical graphs.
    op.execute("""
        CREATE TEMP TABLE refresh_family_backfill ON COMMIT DROP AS
        WITH RECURSIVE chain(jti, family_id, user_id) AS (
            SELECT token.jti, token.id, token.user_id FROM refresh_tokens token
            WHERE NOT EXISTS (SELECT 1 FROM refresh_tokens parent WHERE parent.replaced_by_jti = token.jti)
            UNION
            SELECT child.jti, chain.family_id, chain.user_id
            FROM chain JOIN refresh_tokens parent ON parent.jti = chain.jti
            JOIN refresh_tokens child ON child.jti = parent.replaced_by_jti AND child.user_id = chain.user_id
        ) SELECT jti, family_id, user_id FROM chain
    """)
    connection = op.get_bind()
    total = connection.scalar(sa.text("SELECT count(*) FROM refresh_tokens"))
    mapped, unique = connection.execute(
        sa.text("SELECT count(*), count(DISTINCT jti) FROM refresh_family_backfill")
    ).one()
    if total != mapped or mapped != unique:
        raise RuntimeError(
            "Refresh history is inconsistent; reconcile cycles or merged/cross-user chains before migration"
        )
    op.execute("""
        INSERT INTO refresh_token_families (id, user_id, revoked_at)
        SELECT mapping.family_id, mapping.user_id,
               min(CASE WHEN token.revoked_at IS NOT NULL AND token.replaced_by_jti IS NULL THEN token.revoked_at END)
        FROM refresh_family_backfill mapping JOIN refresh_tokens token ON token.jti = mapping.jti
        GROUP BY mapping.family_id, mapping.user_id
    """)
    op.execute(
        "UPDATE refresh_tokens SET family_id = mapping.family_id FROM refresh_family_backfill mapping WHERE refresh_tokens.jti = mapping.jti"
    )
    op.alter_column("refresh_tokens", "family_id", nullable=False)
    op.create_foreign_key(
        "fk_refresh_tokens_family",
        "refresh_tokens",
        "refresh_token_families",
        ["family_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_constraint("fk_refresh_tokens_family", "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "family_id")
    op.drop_index("ix_refresh_token_families_user_id", table_name="refresh_token_families")
    op.drop_table("refresh_token_families")
