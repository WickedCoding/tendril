from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Issue, IssueTag


def find_surfaces(session: Session, viewed_key: str) -> list[tuple[Issue, list[str]]]:
    """Return (issue, shared_tags) pairs for every cached issue sharing a tag with `viewed_key`.

    Any tagged issue that overlaps on at least one tag surfaces — no opt-in marker.
    The viewed issue itself is excluded. If the viewed issue has no tags, nothing fires.
    Results are ordered by issue key for stable rendering.
    """
    viewed_tags = set(
        session.scalars(select(IssueTag.tag).where(IssueTag.issue_key == viewed_key)).all()
    )
    if not viewed_tags:
        return []

    rows = session.execute(
        select(IssueTag.issue_key, IssueTag.tag)
        .where(
            IssueTag.issue_key != viewed_key,
            IssueTag.tag.in_(viewed_tags),
        )
        .order_by(IssueTag.issue_key, IssueTag.tag)
    ).all()

    grouped: dict[str, list[str]] = {}
    for other_key, tag in rows:
        grouped.setdefault(other_key, []).append(tag)

    result: list[tuple[Issue, list[str]]] = []
    for other_key in sorted(grouped):
        issue = session.get(Issue, other_key)
        if issue is None:
            # Tag row exists but the issue was never cached — skip silently.
            continue
        result.append((issue, grouped[other_key]))
    return result
