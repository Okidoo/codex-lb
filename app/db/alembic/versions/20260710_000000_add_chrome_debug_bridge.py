"""add chrome debug bridge

Revision ID: 20260710_000000_add_chrome_debug_bridge
Revises: 20260707_020000_add_zai_credential_key_id
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260710_000000_add_chrome_debug_bridge"
down_revision = "20260707_020000_add_zai_credential_key_id"
branch_labels = None
depends_on = None


def _has_table(connection: Connection, table_name: str) -> bool:
    return sa.inspect(connection).has_table(table_name)


def _indexes(connection: Connection, table_name: str) -> set[str]:
    if not _has_table(connection, table_name):
        return set()
    return {name for index in sa.inspect(connection).get_indexes(table_name) if (name := index["name"]) is not None}


def _create_index_once(name: str, table_name: str, columns: list[str]) -> None:
    if name not in _indexes(op.get_bind(), table_name):
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "chrome_debug_api_key_grants"):
        op.create_table(
            "chrome_debug_api_key_grants",
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("api_key_id"),
        )

    if not _has_table(bind, "chrome_debug_browsers"):
        op.create_table(
            "chrome_debug_browsers",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("label", sa.String(length=128), nullable=False),
            sa.Column("instance_id", sa.String(length=255), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("extension_version", sa.String(length=64), nullable=True),
            sa.Column("is_revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["api_key_id"], ["chrome_debug_api_key_grants.api_key_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_chrome_debug_browsers_api_key_id", "chrome_debug_browsers", ["api_key_id"])

    if not _has_table(bind, "chrome_debug_agent_tokens"):
        op.create_table(
            "chrome_debug_agent_tokens",
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("browser_id", sa.String(), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["browser_id"], ["chrome_debug_browsers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("token_hash"),
        )
    _create_index_once("ix_chrome_debug_agent_tokens_api_key_id", "chrome_debug_agent_tokens", ["api_key_id"])
    _create_index_once("ix_chrome_debug_agent_tokens_browser_id", "chrome_debug_agent_tokens", ["browser_id"])

    if not _has_table(bind, "chrome_debug_relay_tokens"):
        op.create_table(
            "chrome_debug_relay_tokens",
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("browser_id", sa.String(), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["browser_id"], ["chrome_debug_browsers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("token_hash"),
        )
    _create_index_once("ix_chrome_debug_relay_tokens_api_key_id", "chrome_debug_relay_tokens", ["api_key_id"])
    _create_index_once("ix_chrome_debug_relay_tokens_browser_id", "chrome_debug_relay_tokens", ["browser_id"])

    if not _has_table(bind, "chrome_debug_sessions"):
        op.create_table(
            "chrome_debug_sessions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("browser_id", sa.String(), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=False),
            sa.Column("target_id", sa.Text(), nullable=False),
            sa.Column("state", sa.String(length=32), server_default="active", nullable=False),
            sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["browser_id"], ["chrome_debug_browsers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_chrome_debug_sessions_api_key_id", "chrome_debug_sessions", ["api_key_id"])
    _create_index_once("ix_chrome_debug_sessions_browser_id", "chrome_debug_sessions", ["browser_id"])

    if not _has_table(bind, "chrome_debug_audit_events"):
        op.create_table(
            "chrome_debug_audit_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("api_key_id", sa.String(), nullable=True),
            sa.Column("browser_id", sa.String(), nullable=True),
            sa.Column("session_id", sa.String(), nullable=True),
            sa.Column("target_id", sa.Text(), nullable=True),
            sa.Column("actor_ip", sa.String(length=64), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_chrome_debug_audit_events_api_key_id", "chrome_debug_audit_events", ["api_key_id"])
    _create_index_once("ix_chrome_debug_audit_events_browser_id", "chrome_debug_audit_events", ["browser_id"])
    _create_index_once("ix_chrome_debug_audit_events_event_type", "chrome_debug_audit_events", ["event_type"])


def downgrade() -> None:
    for table_name in (
        "chrome_debug_audit_events",
        "chrome_debug_sessions",
        "chrome_debug_relay_tokens",
        "chrome_debug_agent_tokens",
        "chrome_debug_browsers",
        "chrome_debug_api_key_grants",
    ):
        if _has_table(op.get_bind(), table_name):
            op.drop_table(table_name)
