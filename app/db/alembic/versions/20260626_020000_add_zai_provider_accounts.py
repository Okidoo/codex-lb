"""Add account providers and Z.AI credentials.

Revision ID: 20260626_020000_add_zai_provider_accounts
Revises: 20260626_010000_add_request_logs_upstream_transport
Create Date: 2026-06-26 02:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_020000_add_zai_provider_accounts"
down_revision = "20260626_010000_add_request_logs_upstream_transport"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("accounts", "provider"):
        op.add_column(
            "accounts",
            sa.Column(
                "provider",
                sa.String(),
                nullable=False,
                server_default=sa.text("'openai'"),
            ),
        )

    if not _has_table("zai_credentials"):
        op.create_table(
            "zai_credentials",
            sa.Column(
                "account_id",
                sa.String(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
            sa.Column("api_key_hash", sa.String(), nullable=False, unique=True),
            sa.Column("base_url", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    if _has_table("zai_credentials"):
        op.drop_table("zai_credentials")
    if _has_column("accounts", "provider"):
        op.drop_column("accounts", "provider")
