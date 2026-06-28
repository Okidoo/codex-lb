"""remove model aliases

Revision ID: 20260628_000000_remove_model_aliases
Revises: 20260627_000000_add_model_aliases
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260628_000000_remove_model_aliases"
down_revision = "20260627_000000_add_model_aliases"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name)


def upgrade() -> None:
    if _has_table("model_aliases"):
        op.drop_table("model_aliases")


def downgrade() -> None:
    if not _has_table("model_aliases"):
        op.create_table(
            "model_aliases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("source_model", sa.String(), nullable=False),
            sa.Column("target_model", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "idx_model_aliases_source_model",
            "model_aliases",
            ["source_model"],
            unique=True,
        )
