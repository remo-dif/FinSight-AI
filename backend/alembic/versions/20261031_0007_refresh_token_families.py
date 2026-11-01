"""Persist independent refresh families without changing existing token material.

Revision ID: 20261031_0007
Revises: 20261031_0006
"""

from collections import defaultdict

import sqlalchemy as sa

from alembic import op

revision = "20261031_0007"
down_revision = "20261031_0006"
branch_labels = None
depends_on = None


def _validated_family_mapping(connection):
    rows = (
        connection.execute(
            sa.text("""
            SELECT id, user_id, jti, expires_at, revoked_at, replaced_by_jti
            FROM refresh_tokens
            ORDER BY id
        """)
        )
        .mappings()
        .all()
    )
    now = connection.scalar(sa.text("SELECT CURRENT_TIMESTAMP"))

    rows_by_jti = defaultdict(list)
    for row in rows:
        rows_by_jti[row["jti"]].append(row)
    duplicate_jtis = [jti for jti, matches in rows_by_jti.items() if len(matches) > 1]
    if duplicate_jtis:
        raise RuntimeError(
            "Refresh history is inconsistent; migration aborted: duplicate JTIs "
            f"{', '.join(sorted(duplicate_jtis)[:10])}"
        )

    tokens = {jti: matches[0] for jti, matches in rows_by_jti.items()}
    predecessors = defaultdict(list)
    problems = []

    for token in rows:
        successor_jti = token["replaced_by_jti"]
        if successor_jti is None:
            continue

        successor = tokens.get(successor_jti)
        if successor is None:
            problems.append(
                f"token row {token['id']} references missing successor JTI {successor_jti}"
            )
            continue

        predecessors[successor_jti].append(token["jti"])
        if token["user_id"] != successor["user_id"]:
            problems.append(
                f"successor edge from token row {token['id']} to row {successor['id']} "
                "crosses users"
            )
        if token["revoked_at"] is None:
            problems.append(
                f"unrevoked token row {token['id']} has successor row {successor['id']}"
            )

    for jti, parent_jtis in sorted(predecessors.items()):
        if len(parent_jtis) > 1:
            parent_ids = [str(tokens[parent_jti]["id"]) for parent_jti in sorted(parent_jtis)]
            problems.append(
                f"token row {tokens[jti]['id']} has multiple predecessors {', '.join(parent_ids)}"
            )

    completed = set()
    for start_jti in sorted(tokens):
        path = []
        path_positions = {}
        current_jti = start_jti
        while current_jti in tokens and current_jti not in completed:
            if current_jti in path_positions:
                cycle = path[path_positions[current_jti] :]
                cycle_ids = [str(tokens[jti]["id"]) for jti in cycle]
                problems.append(f"cycle among token rows {', '.join(cycle_ids)}")
                break
            path_positions[current_jti] = len(path)
            path.append(current_jti)
            successor_jti = tokens[current_jti]["replaced_by_jti"]
            if successor_jti is None or successor_jti not in tokens:
                break
            current_jti = successor_jti
        completed.update(path)

    family_by_jti = {}
    roots = sorted(jti for jti in tokens if not predecessors[jti])
    for root_jti in roots:
        family_id = tokens[root_jti]["id"]
        current_jti = root_jti
        active_terminal_tokens = []
        while current_jti in tokens:
            if current_jti in family_by_jti:
                problems.append(
                    f"token row {tokens[current_jti]['id']} is assigned to multiple families"
                )
                break
            token = tokens[current_jti]
            family_by_jti[current_jti] = family_id
            if token["revoked_at"] is None and token["expires_at"] > now:
                if token["replaced_by_jti"] is not None:
                    successor = tokens.get(token["replaced_by_jti"])
                    successor_id = successor["id"] if successor is not None else "unknown"
                    problems.append(
                        f"active token row {token['id']} is nonterminal "
                        f"(successor row {successor_id})"
                    )
                else:
                    active_terminal_tokens.append(token)
            successor_jti = token["replaced_by_jti"]
            if successor_jti is None or successor_jti not in tokens:
                break
            current_jti = successor_jti
        if len(active_terminal_tokens) > 1:
            active_ids = [str(token["id"]) for token in active_terminal_tokens]
            problems.append(
                f"family rooted at token row {tokens[root_jti]['id']} has multiple active "
                f"terminals {', '.join(active_ids)}"
            )

    unassigned = sorted(set(tokens) - set(family_by_jti))
    if unassigned:
        row_ids = [str(tokens[jti]["id"]) for jti in unassigned[:10]]
        problems.append(f"tokens are disconnected or rootless: {', '.join(row_ids)}")

    if problems:
        details = "; ".join(problems[:20])
        if len(problems) > 20:
            details += f"; and {len(problems) - 20} more graph errors"
        raise RuntimeError(f"Refresh history is inconsistent; migration aborted: {details}")

    return [
        {
            "jti": row["jti"],
            "family_id": family_by_jti[row["jti"]],
            "user_id": row["user_id"],
        }
        for row in rows
    ]


def upgrade() -> None:
    connection = op.get_bind()
    family_mapping = _validated_family_mapping(connection)

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
    op.execute("""
        CREATE TEMP TABLE refresh_family_backfill (
            jti varchar(64) PRIMARY KEY,
            family_id uuid NOT NULL,
            user_id uuid NOT NULL
        ) ON COMMIT DROP
    """)
    if family_mapping:
        connection.execute(
            sa.text("""
                INSERT INTO refresh_family_backfill (jti, family_id, user_id)
                VALUES (:jti, :family_id, :user_id)
            """),
            family_mapping,
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
