from __future__ import annotations

from sqlalchemy.orm import Session

from tendril.db.models import Issue
from tendril.jira.fetch import JiraLike, fetch_issue
from tendril.sync.pipeline import upsert_issue


def sync_issue(client: JiraLike, session: Session, key: str) -> Issue:
    """Fetch one issue from JIRA and upsert it (with links & comments) into the cache."""
    dto = fetch_issue(client, key)
    row = upsert_issue(session, dto)
    session.commit()
    return row
