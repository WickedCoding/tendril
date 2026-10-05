"""Keep comment bodies as JIRA sent them.

Before this revision a comment's ADF body was flattened to plain text on sync
(`dto.adf_to_text`), losing line breaks, lists and styling. `comment.body_raw`
now holds the original (ADF dict or wiki string) so it can be rendered at
display time, the same way descriptions are. This backfills it from
`issue.raw_json`, which embeds the issue's most recent comments.

Comment rows not in their issue's `raw_json` (beyond the ~20 JIRA embeds, or
deleted in JIRA since) stay NULL and fall back to the flattened `body` until
the next `tendril sync issue KEY` rewrites them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("comment") as batch:
        batch.add_column(sa.Column("body_raw", sa.JSON(), nullable=True))

    bind = op.get_bind()
    comment = sa.table(
        "comment",
        sa.column("id", sa.String),
        sa.column("body_raw", sa.JSON),
    )
    rows = bind.execute(sa.text("SELECT raw_json FROM issue")).all()
    for (raw,) in rows:
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        comments = ((payload.get("fields") or {}).get("comment") or {}).get("comments") or []
        for c in comments:
            if not isinstance(c, dict) or c.get("id") is None or c.get("body") is None:
                continue
            bind.execute(
                comment.update().where(comment.c.id == str(c["id"])).values(body_raw=c["body"])
            )


def downgrade() -> None:
    with op.batch_alter_table("comment") as batch:
        batch.drop_column("body_raw")
