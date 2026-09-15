"""rollover state: issue.story_points, issue.skills, rollover_attempt, rollover_log

Adds first-class Story Points and Skills columns to issue (backfilled on next
sync — existing rows land with NULL / empty list until then), plus two new
tables that carry the sprint-rollover state and its success history.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("issue") as batch:
        batch.add_column(sa.Column("story_points", sa.Float(), nullable=True))
        batch.add_column(
            sa.Column("skills", sa.JSON(), nullable=False, server_default="[]")
        )

    op.create_table(
        "rollover_attempt",
        sa.Column("source_sprint_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("target_sprint_id", sa.Integer(), nullable=False),
        sa.Column("selected_issue_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("moved_issue_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("completed_step", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "rollover_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_sprint_id", sa.Integer(), nullable=False),
        sa.Column("source_sprint_name", sa.String(), nullable=False),
        sa.Column("target_sprint_id", sa.Integer(), nullable=False),
        sa.Column("target_sprint_name", sa.String(), nullable=False),
        sa.Column("moved_issue_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rollover_log")
    op.drop_table("rollover_attempt")
    with op.batch_alter_table("issue") as batch:
        batch.drop_column("skills")
        batch.drop_column("story_points")
