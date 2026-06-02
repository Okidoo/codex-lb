"""merge account proxy and workspace heads

Revision ID: 20260602_080000_merge_account_proxy_and_workspace_heads
Revises: 20260601_020000_merge_account_proxy_and_upstream_proxy_heads,
    20260602_060000_merge_account_workspace_and_failure_heads
Create Date: 2026-06-02 08:00:00.000000
"""

from __future__ import annotations

revision = "20260602_080000_merge_account_proxy_and_workspace_heads"
down_revision = (
    "20260601_020000_merge_account_proxy_and_upstream_proxy_heads",
    "20260602_060000_merge_account_workspace_and_failure_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
