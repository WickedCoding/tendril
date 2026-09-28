from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from tendril.db.models import Issue, IssueSprint, IssueTag, Sprint, User
from tendril.sync.commands import find_issues


def _seed(session: Session, load_fixture) -> None:
    """PROJ-1 (In Progress, Jane, Sprint 1, tags logo+infra), PROJ-2 (Done, unassigned, no sprint)."""
    from tendril.jira.dto import normalize_issue
    from tendril.sync.pipeline import upsert_issue
    upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
    upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
    session.flush()

    session.merge(User(account_id="acc-jane", display_name="Jane Doe"))
    p1 = session.get(Issue, "PROJ-1")
    p2 = session.get(Issue, "PROJ-2")
    assert p1 is not None and p2 is not None
    p1.status, p1.assignee_account_id = "In Progress", "acc-jane"
    p2.status, p2.assignee_account_id = "Done", None

    session.add(Sprint(id=1, name="Sprint 1", state="active"))
    session.add(Sprint(id=2, name="Sprint 1", state="closed"))
    session.add(IssueSprint(issue_key="PROJ-1", sprint_id=1))
    session.add(IssueSprint(issue_key="PROJ-1", sprint_id=2))
    session.add(IssueTag(issue_key="PROJ-1", tag="logo"))
    session.add(IssueTag(issue_key="PROJ-1", tag="infra"))
    session.commit()


def _keys(issues: list[Issue]) -> set[str]:
    return {i.key for i in issues}


def test_requires_at_least_one_filter(session: Session) -> None:
    with pytest.raises(ValueError):
        find_issues(session)
    with pytest.raises(ValueError):
        find_issues(session, statuses=[], tags=[])


def test_each_filter_alone_is_case_insensitive(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    assert _keys(find_issues(session, statuses=["in progress"])) == {"PROJ-1"}
    assert _keys(find_issues(session, projects=["proj"])) == {"PROJ-1", "PROJ-2"}
    assert _keys(find_issues(session, assignee="JANE DOE")) == {"PROJ-1"}
    assert _keys(find_issues(session, sprint="sprint 1")) == {"PROJ-1"}
    assert _keys(find_issues(session, tags=["LOGO"])) == {"PROJ-1"}


def test_matches_are_exact_not_partial(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    assert find_issues(session, statuses=["Progress"]) == []
    assert find_issues(session, assignee="Jane") == []
    assert find_issues(session, sprint="Sprint") == []
    assert find_issues(session, tags=["log"]) == []


def test_list_values_are_ored(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    assert _keys(find_issues(session, statuses=["Done", "In Progress"])) == {"PROJ-1", "PROJ-2"}
    assert _keys(find_issues(session, projects=["OTHER", "PROJ"])) == {"PROJ-1", "PROJ-2"}
    assert _keys(find_issues(session, tags=["missing", "infra"])) == {"PROJ-1"}


def test_filters_are_anded(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    assert _keys(find_issues(session, projects=["PROJ"], statuses=["Done"])) == {"PROJ-2"}
    assert find_issues(session, statuses=["Done"], tags=["logo"]) == []
    assert find_issues(session, statuses=["In Progress"], projects=["OTHER"]) == []


def test_project_does_not_bleed_into_longer_prefix(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    for key in ("PROJX-1", "PR_J-1", "PRXJ-1"):
        session.add(Issue(key=key, summary="other project", status="Done", raw_json={},
                          last_synced_at=datetime.now(timezone.utc)))
    session.commit()
    assert _keys(find_issues(session, projects=["PROJ"])) == {"PROJ-1", "PROJ-2"}
    # `_` must be literal, not a LIKE wildcard.
    assert _keys(find_issues(session, projects=["PR_J"])) == {"PR_J-1"}


def test_multiple_matching_tags_or_sprints_do_not_duplicate(session: Session, load_fixture) -> None:
    _seed(session, load_fixture)
    assert [i.key for i in find_issues(session, tags=["logo", "infra"])] == ["PROJ-1"]
    assert [i.key for i in find_issues(session, sprint="Sprint 1")] == ["PROJ-1"]


# --- CLI -------------------------------------------------------------------

@pytest.fixture
def cli_db(isolated_xdg, load_fixture):
    from sqlalchemy.orm import sessionmaker
    from tendril.db.engine import build_engine
    from tendril.db.schema import init_schema

    engine = build_engine()
    init_schema(engine)
    with sessionmaker(bind=engine, expire_on_commit=False, future=True)() as s:
        _seed(s, load_fixture)
    engine.dispose()


def test_cli_without_filters_is_a_usage_error(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["search"])
    assert result.exit_code == 2
    result = CliRunner().invoke(app, ["search", "--tag=,", "--sprint= "])
    assert result.exit_code == 2


def test_cli_json_shape(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["search", "--project=proj", "--tag=logo, missing", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [i["key"] for i in payload["issues"]] == ["PROJ-1"]
    issue = payload["issues"][0]
    assert issue["project"] == "PROJ"
    assert issue["status"] == "In Progress"
    assert issue["assignee"] == "Jane Doe"
    assert issue["sprints"] == ["Sprint 1", "Sprint 1"]
    assert issue["tags"] == ["infra", "logo"]
    assert set(issue) == {
        "key", "project", "summary", "status", "issuetype",
        "assignee", "sprints", "tags", "updated",
    }


def test_cli_json_empty_result(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["search", "--status=Nope", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"issues": []}
