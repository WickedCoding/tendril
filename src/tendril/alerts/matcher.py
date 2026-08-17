from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Issue, IssueAlert, IssueTag


def find_surfaces(session: Session, viewed_key: str) -> list[tuple[Issue, list[str]]]:
    """Return (alert_issue, shared_tags) pairs for every alert that fires on `viewed_key`.

    An alert fires when the alert-owning issue shares at least one tag with the viewed issue.
    The viewed issue itself is excluded. If the viewed issue has no tags, nothing fires.
    Results are ordered by the alert-owning issue's key for stable rendering.
    """
    viewed_tags = set(
        session.scalars(select(IssueTag.tag).where(IssueTag.issue_key == viewed_key)).all()
    )
    if not viewed_tags:
        return []

    rows = session.execute(
        select(IssueAlert.issue_key, IssueTag.tag)
        .join(IssueTag, IssueTag.issue_key == IssueAlert.issue_key)
        .where(
            IssueAlert.issue_key != viewed_key,
            IssueTag.tag.in_(viewed_tags),
        )
        .order_by(IssueAlert.issue_key, IssueTag.tag)
    ).all()

    grouped: dict[str, list[str]] = {}
    for alert_key, tag in rows:
        grouped.setdefault(alert_key, []).append(tag)

    result: list[tuple[Issue, list[str]]] = []
    for alert_key in sorted(grouped):
        issue = session.get(Issue, alert_key)
        if issue is None:
            # Alert row exists but the issue was never cached — skip silently.
            continue
        result.append((issue, grouped[alert_key]))
    return result
