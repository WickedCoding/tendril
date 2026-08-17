from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from tendril.db.models import Comment, Issue, IssueLink, User
from tendril.jira.dto import IssueDTO, UserDTO


def _upsert_user(session: Session, dto: UserDTO | None) -> str | None:
    if dto is None:
        return None
    existing = session.get(User, dto.account_id)
    if existing is None:
        session.add(User(
            account_id=dto.account_id,
            display_name=dto.display_name,
            email=dto.email,
        ))
    else:
        if dto.display_name is not None:
            existing.display_name = dto.display_name
        if dto.email is not None:
            existing.email = dto.email
    return dto.account_id


def upsert_issue(session: Session, dto: IssueDTO) -> Issue:
    """Upsert the Issue row and all its links + comments. Replaces links wholesale."""
    assignee_id = _upsert_user(session, dto.assignee)
    reporter_id = _upsert_user(session, dto.reporter)

    row = session.get(Issue, dto.key)
    if row is None:
        row = Issue(key=dto.key, raw_json=dto.raw, last_synced_at=datetime.now(timezone.utc))
        session.add(row)

    row.summary = dto.summary
    row.status = dto.status
    row.issuetype = dto.issuetype
    row.assignee_account_id = assignee_id
    row.reporter_account_id = reporter_id
    row.created = dto.created
    row.updated = dto.updated
    row.duedate = dto.duedate
    row.parent_key = dto.parent_key
    row.sprint_name = dto.sprint_name
    row.raw_json = dto.raw
    row.last_synced_at = datetime.now(timezone.utc)

    _replace_links(session, dto)
    _upsert_comments(session, dto)
    return row


def _replace_links(session: Session, dto: IssueDTO) -> None:
    """Wipe this issue's outgoing/incoming links and reinsert from the DTO.

    JIRA's issuelinks payload is the current truth; deleted links won't appear,
    so a wholesale replace is safer than trying to diff.
    """
    session.execute(delete(IssueLink).where(IssueLink.source_key == dto.key))
    for link in dto.links:
        session.add(IssueLink(
            source_key=dto.key,
            target_key=link.target_key,
            link_type=link.link_type,
            direction=link.direction,
            jira_link_id=link.jira_link_id,
        ))


def _upsert_comments(session: Session, dto: IssueDTO) -> None:
    for c in dto.comments:
        _upsert_user(session, c.author)
        row = session.get(Comment, c.id)
        if row is None:
            session.add(Comment(
                id=c.id,
                issue_key=dto.key,
                author_account_id=c.author.account_id if c.author else None,
                body=c.body,
                created=c.created,
                updated=c.updated,
            ))
        else:
            row.body = c.body
            row.updated = c.updated
            row.author_account_id = c.author.account_id if c.author else row.author_account_id
