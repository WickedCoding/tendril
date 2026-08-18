"""initial schema

Single baseline migration; there was no prior migration history. Downgrade
drops everything — reserved for `alembic downgrade base` during dev.

Revision ID: 0001
Revises:
Create Date: 2026-08-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_sync_state",
        sa.Column("project_key", sa.String(), primary_key=True),
        sa.Column("last_full_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_incremental_sync_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "user",
        sa.Column("account_id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
    )

    op.create_table(
        "issue",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("issuetype", sa.String(), nullable=True),
        sa.Column("assignee_account_id", sa.String(), nullable=True),
        sa.Column("reporter_account_id", sa.String(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=True),
        sa.Column("updated", sa.DateTime(), nullable=True),
        sa.Column("duedate", sa.Date(), nullable=True),
        sa.Column("parent_key", sa.String(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "issue_link",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("link_type", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("jira_link_id", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "source_key", "target_key", "link_type", "direction",
            name="uq_issue_link",
        ),
    )

    op.create_table(
        "comment",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("issue_key", sa.String(), nullable=False),
        sa.Column("author_account_id", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=True),
        sa.Column("updated", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "watchlist_entry",
        sa.Column("issue_key", sa.String(), primary_key=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "issue_tag",
        sa.Column("issue_key", sa.String(), primary_key=True),
        sa.Column("tag", sa.String(), primary_key=True),
    )

    op.create_table(
        "issue_alert",
        sa.Column("issue_key", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sprint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("complete_date", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "issue_sprint",
        sa.Column("issue_key", sa.String(), primary_key=True),
        sa.Column("sprint_id", sa.Integer(), primary_key=True),
    )
    op.create_index("ix_issue_sprint_sprint_id", "issue_sprint", ["sprint_id"])

    op.create_table(
        "link_type",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("outward", sa.String(), nullable=False),
        sa.Column("inward", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("link_type")
    op.drop_index("ix_issue_sprint_sprint_id", table_name="issue_sprint")
    op.drop_table("issue_sprint")
    op.drop_table("sprint")
    op.drop_table("issue_alert")
    op.drop_table("issue_tag")
    op.drop_table("watchlist_entry")
    op.drop_table("comment")
    op.drop_table("issue_link")
    op.drop_table("issue")
    op.drop_table("user")
    op.drop_table("project_sync_state")
