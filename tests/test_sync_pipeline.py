from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Comment, Issue, IssueLink, IssueSprint, Sprint, User
from tendril.jira.dto import normalize_issue
from tendril.sync.commands import list_sprint_issues, sync_issue
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


# ---------- sprint parsing + persistence ----------


def _issue_with_sprints(key: str, assignee: str | None, sprints, summary: str = "s") -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Task"},
            "assignee": {"accountId": assignee} if assignee else None,
            "customfield_10020": sprints,
        },
    }


def test_normalize_issue_ignores_sprint_field_when_id_not_configured() -> None:
    payload = _issue_with_sprints("X-1", "me", [{"id": 1, "name": "S1", "state": "active"}])
    dto = normalize_issue(payload)  # no sprint_field_id -> empty
    assert dto.sprints == []


def test_normalize_issue_parses_modern_sprint_dicts() -> None:
    payload = _issue_with_sprints("X-1", "me", [
        {
            "id": 42, "name": "Sprint 17", "state": "active",
            "boardId": 5, "goal": "ship it",
            "startDate": "2026-08-11T09:00:00.000Z",
            "endDate": "2026-08-25T09:00:00.000Z",
        },
        {
            "id": 41, "name": "Sprint 16", "state": "closed",
            "boardId": 5,
            "startDate": "2026-07-28T09:00:00.000Z",
            "endDate": "2026-08-11T09:00:00.000Z",
            "completeDate": "2026-08-11T09:15:23.456Z",
        },
    ])
    dto = normalize_issue(payload, sprint_field_id="customfield_10020")
    assert len(dto.sprints) == 2
    active = next(s for s in dto.sprints if s.state == "active")
    assert active.id == 42
    assert active.name == "Sprint 17"
    assert active.board_id == 5
    assert active.goal == "ship it"
    assert active.start_date is not None and active.end_date is not None
    closed = next(s for s in dto.sprints if s.state == "closed")
    assert closed.complete_date is not None


def test_normalize_issue_parses_legacy_sprint_toString() -> None:
    legacy = (
        "com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c["
        "id=42,rapidViewId=5,state=ACTIVE,name=Legacy 17,"
        "startDate=2026-08-11T09:00:00.000Z,endDate=2026-08-25T09:00:00.000Z,"
        "completeDate=<null>,goal=Ship the sprint watchlist]"
    )
    payload = _issue_with_sprints("X-1", "me", [legacy])
    dto = normalize_issue(payload, sprint_field_id="customfield_10020")
    assert len(dto.sprints) == 1
    s = dto.sprints[0]
    assert s.id == 42
    assert s.name == "Legacy 17"
    assert s.state == "active"  # lowercased
    assert s.complete_date is None  # <null> dropped


def test_normalize_issue_handles_null_sprint_field() -> None:
    payload = _issue_with_sprints("X-1", "me", None)
    dto = normalize_issue(payload, sprint_field_id="customfield_10020")
    assert dto.sprints == []


def test_upsert_replaces_sprints_wholesale(session: Session) -> None:
    dto = normalize_issue(
        _issue_with_sprints("X-1", "acc-me", [
            {"id": 1, "name": "S1", "state": "active"},
            {"id": 2, "name": "S2", "state": "closed"},
        ]),
        sprint_field_id="customfield_10020",
    )
    upsert_issue(session, dto)
    session.commit()

    sprints = {r.sprint_id for r in session.query(IssueSprint).filter_by(issue_key="X-1").all()}
    assert sprints == {1, 2}

    # Second sync: S2 dropped, S3 added. Wholesale replace of the join rows.
    dto2 = normalize_issue(
        _issue_with_sprints("X-1", "acc-me", [
            {"id": 1, "name": "S1 (renamed)", "state": "closed"},
            {"id": 3, "name": "S3", "state": "active"},
        ]),
        sprint_field_id="customfield_10020",
    )
    upsert_issue(session, dto2)
    session.commit()

    sprints_after = {r.sprint_id for r in session.query(IssueSprint).filter_by(issue_key="X-1").all()}
    assert sprints_after == {1, 3}

    # Sprint metadata refreshed on the shared row.
    s1 = session.get(Sprint, 1)
    assert s1 is not None
    assert s1.name == "S1 (renamed)"
    assert s1.state == "closed"


# ---------- story points + skills parsing + persistence ----------


def _issue_with_sp_and_skills(
    key: str,
    story_points: object,
    skills: object,
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": "s",
            "status": {"name": "To Do"},
            "issuetype": {"name": "Task"},
            "customfield_10032": story_points,
            "customfield_10134": skills,
        },
    }


def test_normalize_ignores_sp_and_skills_when_field_ids_not_configured() -> None:
    payload = _issue_with_sp_and_skills("X-1", 5, [{"value": "Backend"}])
    dto = normalize_issue(payload)
    assert dto.story_points is None
    assert dto.skills == []


def test_normalize_parses_numeric_story_points() -> None:
    payload = _issue_with_sp_and_skills("X-1", 5, None)
    dto = normalize_issue(payload, story_points_field_id="customfield_10032")
    assert dto.story_points == 5.0


def test_normalize_story_points_tolerates_string_and_null() -> None:
    dto_str = normalize_issue(
        _issue_with_sp_and_skills("X-1", "3.5", None),
        story_points_field_id="customfield_10032",
    )
    assert dto_str.story_points == 3.5
    dto_none = normalize_issue(
        _issue_with_sp_and_skills("X-1", None, None),
        story_points_field_id="customfield_10032",
    )
    assert dto_none.story_points is None
    dto_junk = normalize_issue(
        _issue_with_sp_and_skills("X-1", "not-a-number", None),
        story_points_field_id="customfield_10032",
    )
    assert dto_junk.story_points is None


def test_normalize_parses_skills_from_option_objects() -> None:
    payload = _issue_with_sp_and_skills(
        "X-1", None,
        [{"value": "Backend", "id": "1"}, {"value": "Frontend", "id": "2"}],
    )
    dto = normalize_issue(payload, skills_field_id="customfield_10134")
    assert dto.skills == ["Backend", "Frontend"]


def test_normalize_parses_skills_from_flat_strings() -> None:
    payload = _issue_with_sp_and_skills("X-1", None, ["Backend", "Data"])
    dto = normalize_issue(payload, skills_field_id="customfield_10134")
    assert dto.skills == ["Backend", "Data"]


def test_upsert_persists_story_points_and_skills(session: Session) -> None:
    dto = normalize_issue(
        _issue_with_sp_and_skills(
            "X-1", 8, [{"value": "Backend"}, {"value": "Frontend"}],
        ),
        story_points_field_id="customfield_10032",
        skills_field_id="customfield_10134",
    )
    upsert_issue(session, dto)
    session.commit()

    row = session.get(Issue, "X-1")
    assert row is not None
    assert row.story_points == 8.0
    assert row.skills == ["Backend", "Frontend"]

    # Re-sync with a different skill set overwrites the list wholesale.
    dto2 = normalize_issue(
        _issue_with_sp_and_skills("X-1", None, [{"value": "Data"}]),
        story_points_field_id="customfield_10032",
        skills_field_id="customfield_10134",
    )
    upsert_issue(session, dto2)
    session.commit()
    row = session.get(Issue, "X-1")
    assert row is not None
    assert row.story_points is None
    assert row.skills == ["Data"]


# ---------- rollover tables ----------


def test_rollover_tables_are_reachable(session: Session) -> None:
    from datetime import datetime, timezone
    from tendril.db.models import RolloverAttempt, RolloverLog

    now = datetime.now(timezone.utc)
    session.add(RolloverAttempt(
        source_sprint_id=1,
        target_sprint_id=2,
        selected_issue_keys=["A-1", "A-2"],
        moved_issue_keys=["A-1"],
        completed_step=None,
        error=None,
        created_at=now,
        updated_at=now,
    ))
    session.add(RolloverLog(
        source_sprint_id=1,
        source_sprint_name="Sprint 16",
        target_sprint_id=2,
        target_sprint_name="Sprint 17",
        moved_issue_keys=["A-1", "A-2"],
        committed_at=now,
    ))
    session.commit()

    attempt = session.get(RolloverAttempt, 1)
    assert attempt is not None
    assert attempt.selected_issue_keys == ["A-1", "A-2"]
    assert attempt.moved_issue_keys == ["A-1"]

    logs = list(session.query(RolloverLog).all())
    assert len(logs) == 1
    assert logs[0].source_sprint_name == "Sprint 16"


def test_list_sprint_issues_returns_every_issue_in_an_active_sprint(session: Session) -> None:
    mine_active = normalize_issue(
        _issue_with_sprints("X-1", "acc-me",
            [{"id": 10, "name": "Now", "state": "active"}], summary="mine active"),
        sprint_field_id="customfield_10020",
    )
    mine_closed = normalize_issue(
        _issue_with_sprints("X-2", "acc-me",
            [{"id": 11, "name": "Past", "state": "closed"}], summary="mine closed"),
        sprint_field_id="customfield_10020",
    )
    other_active = normalize_issue(
        _issue_with_sprints("X-3", "acc-other",
            [{"id": 10, "name": "Now", "state": "active"}], summary="other active"),
        sprint_field_id="customfield_10020",
    )
    unassigned_active = normalize_issue(
        _issue_with_sprints("X-4", None,
            [{"id": 10, "name": "Now", "state": "active"}], summary="unassigned active"),
        sprint_field_id="customfield_10020",
    )
    for d in (mine_active, mine_closed, other_active, unassigned_active):
        upsert_issue(session, d)
    session.commit()

    result = list_sprint_issues(session)
    keys = {i.key for i, _ in result}
    # Active-sprint issues from everyone (mine, other, unassigned) — but not the closed-sprint one.
    assert keys == {"X-1", "X-3", "X-4"}
    assert all(s.name == "Now" for _, s in result)
