from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Comment, Issue, IssueLink, User
from tendril.jira.dto import normalize_issue
from tendril.sync.commands import sync_issue
from tendril.sync.pipeline import upsert_issue


def test_normalize_issue_extracts_flat_dto(load_fixture) -> None:
    dto = normalize_issue(load_fixture("issue_sample.json"))
    assert dto.key == "PROJ-1"
    assert dto.summary == "First cached issue"
    assert dto.status == "In Progress"
    assert dto.issuetype == "Task"
    assert dto.assignee and dto.assignee.account_id == "acc-alice"
    assert dto.reporter and dto.reporter.account_id == "acc-bob"
    assert dto.duedate == date(2026, 9, 1)
    assert dto.parent_key == "PROJ-100"


def test_normalize_issue_flattens_links_by_direction(load_fixture) -> None:
    dto = normalize_issue(load_fixture("issue_sample.json"))
    assert len(dto.links) == 2
    outward = next(l for l in dto.links if l.direction == "outward")
    inward = next(l for l in dto.links if l.direction == "inward")
    assert outward.link_type == "Blocks"
    assert outward.target_key == "PROJ-2"
    assert inward.link_type == "Relates"
    assert inward.target_key == "PROJ-3"


def test_normalize_issue_flattens_adf_comment_body(load_fixture) -> None:
    dto = normalize_issue(load_fixture("issue_sample.json"))
    bodies = {c.id: c.body for c in dto.comments}
    assert bodies["30001"] == "Kicking this off."
    assert bodies["30002"] == "Second comment in ADF."


def test_upsert_issue_persists_and_replaces_links(session: Session, load_fixture) -> None:
    dto = normalize_issue(load_fixture("issue_sample.json"))
    upsert_issue(session, dto)
    session.commit()

    issue = session.get(Issue, "PROJ-1")
    assert issue is not None
    assert issue.summary == "First cached issue"
    assert issue.assignee_account_id == "acc-alice"

    users = {u.account_id for u in session.scalars(select(User)).all()}
    assert {"acc-alice", "acc-bob", "acc-carol"} <= users

    links = session.scalars(select(IssueLink).where(IssueLink.source_key == "PROJ-1")).all()
    assert len(links) == 2

    comments = session.scalars(select(Comment).where(Comment.issue_key == "PROJ-1")).all()
    assert len(comments) == 2

    # Re-syncing must not double-insert links.
    upsert_issue(session, dto)
    session.commit()
    links_after = session.scalars(select(IssueLink).where(IssueLink.source_key == "PROJ-1")).all()
    assert len(links_after) == 2


def test_sync_issue_end_to_end(session: Session, load_fixture, fake_jira_class) -> None:
    client = fake_jira_class({"PROJ-1": load_fixture("issue_sample.json")})
    row = sync_issue(client, session, "PROJ-1")
    assert row.key == "PROJ-1"
    assert session.get(Issue, "PROJ-1") is not None
