from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tendril.db.models import IssueAlert, IssueTag


def _normalize(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        s = t.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def add_tags(session: Session, key: str, tags: list[str]) -> list[IssueTag]:
    """Add tags to an issue. Idempotent — existing (key, tag) rows are left alone."""
    wanted = _normalize(tags)
    if not wanted:
        return list(session.scalars(select(IssueTag).where(IssueTag.issue_key == key)).all())
    existing = {
        row.tag for row in session.scalars(
            select(IssueTag).where(IssueTag.issue_key == key, IssueTag.tag.in_(wanted))
        )
    }
    for t in wanted:
        if t not in existing:
            session.add(IssueTag(issue_key=key, tag=t))
    session.commit()
    return list(session.scalars(select(IssueTag).where(IssueTag.issue_key == key)).all())


def remove_tags(session: Session, key: str, tags: list[str]) -> int:
    """Remove named tags from an issue. Returns rows deleted."""
    wanted = _normalize(tags)
    if not wanted:
        return 0
    result = session.execute(
        delete(IssueTag).where(IssueTag.issue_key == key, IssueTag.tag.in_(wanted))
    )
    session.commit()
    return int(result.rowcount or 0)


def set_tags(session: Session, key: str, tags: list[str]) -> list[IssueTag]:
    """Replace the full tag set for an issue. Empty list clears all tags.

    The bulk-write path an LLM would use to reconcile a whole issue's tags in one shot.
    """
    wanted = _normalize(tags)
    session.execute(delete(IssueTag).where(IssueTag.issue_key == key))
    for t in wanted:
        session.add(IssueTag(issue_key=key, tag=t))
    session.commit()
    return list(session.scalars(select(IssueTag).where(IssueTag.issue_key == key)).all())


def list_tags_for(session: Session, key: str) -> list[str]:
    return sorted(
        session.scalars(select(IssueTag.tag).where(IssueTag.issue_key == key)).all()
    )


def list_all_tagged(session: Session) -> list[tuple[str, list[str]]]:
    """Every tagged issue with its tags, sorted for stable output."""
    grouped: dict[str, list[str]] = {}
    for issue_key, tag in session.execute(
        select(IssueTag.issue_key, IssueTag.tag).order_by(IssueTag.issue_key, IssueTag.tag)
    ):
        grouped.setdefault(issue_key, []).append(tag)
    return [(k, grouped[k]) for k in sorted(grouped)]


def mark_alert(session: Session, key: str) -> IssueAlert:
    """Mark an issue as an alert. Idempotent."""
    existing = session.get(IssueAlert, key)
    if existing is not None:
        return existing
    row = IssueAlert(issue_key=key, created_at=datetime.now(timezone.utc))
    session.add(row)
    session.commit()
    return row


def unmark_alert(session: Session, key: str) -> bool:
    """Remove the alert marker. Returns True if a row was deleted."""
    existing = session.get(IssueAlert, key)
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def list_alerts(session: Session) -> list[IssueAlert]:
    return list(session.scalars(select(IssueAlert).order_by(IssueAlert.issue_key)).all())


def is_alert(session: Session, key: str) -> bool:
    return session.get(IssueAlert, key) is not None
