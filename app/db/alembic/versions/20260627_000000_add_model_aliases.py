"""add model aliases

Revision ID: 20260627_000000_add_model_aliases
Revises: 20260626_020000_add_zai_provider_accounts
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

from app.core.model_aliases import DEFAULT_MODEL_ALIAS_SOURCE, DEFAULT_MODEL_ALIAS_TARGET

revision = "20260627_000000_add_model_aliases"
down_revision = "20260626_020000_add_zai_provider_accounts"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name)


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")}


def upgrade() -> None:
    if not _has_table("model_aliases"):
        op.create_table(
            "model_aliases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("source_model", sa.String(), nullable=False),
            sa.Column("target_model", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if "idx_model_aliases_source_model" not in _indexes("model_aliases"):
        op.create_index(
            "idx_model_aliases_source_model",
            "model_aliases",
            ["source_model"],
            unique=True,
        )

    aliases = sa.table(
        "model_aliases",
        sa.column("id", sa.String()),
        sa.column("source_model", sa.String()),
        sa.column("target_model", sa.String()),
        sa.column("enabled", sa.Boolean()),
    )
    bind = op.get_bind()
    existing = bind.execute(
        sa.select(aliases.c.id).where(aliases.c.source_model == DEFAULT_MODEL_ALIAS_SOURCE)
    ).first()
    if existing is None:
        bind.execute(
            aliases.insert().values(
                id=str(uuid.uuid4()),
                source_model=DEFAULT_MODEL_ALIAS_SOURCE,
                target_model=DEFAULT_MODEL_ALIAS_TARGET,
                enabled=True,
            )
        )


def downgrade() -> None:
    if _has_table("model_aliases"):
        op.drop_table("model_aliases")
