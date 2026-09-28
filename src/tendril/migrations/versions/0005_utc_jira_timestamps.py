"""Store JIRA issue/comment timestamps as UTC.

Before this revision the offset JIRA sends (`2026-06-23T14:17:28.806+0200`)
was dropped on write, so `issue.created/updated` and `comment.created/updated`
held the JIRA user's wall-clock time — `+0100` or `+0200` depending on DST.
Every other datetime column was already UTC. This re-derives the four columns
from `issue.raw_json`, the untouched fetch payload.

Comment rows whose id no longer appears in their issue's `raw_json` (deleted
in JIRA after the last fetch) can't be re-derived and are left as they are.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _parse(value: Any, *, to_utc: bool) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    if to_utc:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _rewrite(*, to_utc: bool) -> None:
    bind = op.get_bind()
    issue = sa.table(
        "issue",
        sa.column("key", sa.String),
        sa.column("created", sa.DateTime),
        sa.column("updated", sa.DateTime),
    )
    comment = sa.table(
        "comment",
        sa.column("id", sa.String),
        sa.column("created", sa.DateTime),
        sa.column("updated", sa.DateTime),
    )
    rows = bind.execute(sa.text("SELECT key, raw_json FROM issue")).all()
    for key, raw in rows:
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        fields = payload.get("fields") or {}
        bind.execute(
            issue.update().where(issue.c.key == key).values(
                created=_parse(fields.get("created"), to_utc=to_utc),
                updated=_parse(fields.get("updated"), to_utc=to_utc),
            )
        )
        comments = (fields.get("comment") or {}).get("comments") or []
        for c in comments:
            if not isinstance(c, dict) or c.get("id") is None:
                continue
            bind.execute(
                comment.update().where(comment.c.id == str(c["id"])).values(
                    created=_parse(c.get("created"), to_utc=to_utc),
                    updated=_parse(c.get("updated"), to_utc=to_utc),
                )
            )


def upgrade() -> None:
    _rewrite(to_utc=True)


def downgrade() -> None:
    _rewrite(to_utc=False)
