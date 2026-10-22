from __future__ import annotations

from rich.text import Text
from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Comment
from tendril.db.users import format_user
from tendril.jira.render import render_body
from tendril.text import local_time


def issue_comments(session: Session, issue_key: str) -> list[Comment]:
    """Cached comments for one issue, oldest first."""
    return list(session.scalars(
        select(Comment).where(Comment.issue_key == issue_key).order_by(Comment.created)
    ).all())


def comment_body(comment: Comment) -> Text:
    # Rows synced before migration 0006 may lack the raw body; the flattened text still reads.
    body = render_body(comment.body_raw) if comment.body_raw is not None else None
    return body if body is not None else Text(comment.body or "")


def format_comments(comments: list[Comment], names: dict[str, str]) -> Text:
    if not comments:
        return Text("[no comments]")
    blocks: list[Text] = []
    for c in comments:
        author = format_user(c.author_account_id, names) if c.author_account_id else "unknown"
        header = Text(f"— {author} · {local_time(c.created, missing='')}")
        blocks.append(Text("\n").join([header, comment_body(c)]))
    return Text("\n\n").join(blocks)
