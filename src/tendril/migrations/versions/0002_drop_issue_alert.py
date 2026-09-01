"""drop issue_alert table

The alert marker was removed — every tagged issue with a shared tag now surfaces
on its own. The table and its data go with it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("issue_alert")


def downgrade() -> None:
    op.create_table(
        "issue_alert",
        sa.Column("issue_key", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
