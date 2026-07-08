"""merge zai alias removal and model sources heads

Revision ID: 20260707_010000_merge_zai_alias_removal_and_model_sources_heads
Revises: 20260628_000000_remove_model_aliases, 20260707_000000_merge_model_sources_and_session_ttl
Create Date: 2026-07-07 01:00:00.000000
"""

from __future__ import annotations

revision = "20260707_010000_merge_zai_alias_removal_and_model_sources_heads"
down_revision = (
    "20260628_000000_remove_model_aliases",
    "20260707_000000_merge_model_sources_and_session_ttl",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
