"""rollover_attempt.target_order_keys

Persists the exact order the target sprint should end up in after a rollover.
Pushed to JIRA in a new `rank_issues` step so the sprint's display order
matches the two-panel preview.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("rollover_attempt") as batch:
        batch.add_column(
            sa.Column(
                "target_order_keys",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("rollover_attempt") as batch:
        batch.drop_column("target_order_keys")
