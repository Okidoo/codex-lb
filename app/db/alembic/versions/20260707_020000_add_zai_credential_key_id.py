"""add zai credential key id

Revision ID: 20260707_020000_add_zai_credential_key_id
Revises: 20260707_010000_merge_zai_alias_removal_and_model_sources_heads
Create Date: 2026-07-07 02:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260707_020000_add_zai_credential_key_id"
down_revision = "20260707_010000_merge_zai_alias_removal_and_model_sources_heads"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("zai_credentials", "key_id"):
        op.add_column("zai_credentials", sa.Column("key_id", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("zai_credentials", "key_id"):
        op.drop_column("zai_credentials", "key_id")
