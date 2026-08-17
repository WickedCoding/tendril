from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Issue, ProjectSyncState, WatchlistEntry
from tendril.sync.commands import (
    add_to_watchlist,
    incremental_sync,
    list_watchlist,
    remove_from_watchlist,
    sync_project,
)


def test_add_is_idempotent_and_preserves_position(session: Session) -> None:
    entries1, _ = add_to_watchlist(session, ["PROJ-1", "PROJ-2"])
    entries2, _ = add_to_watchlist(session, ["PROJ-1", "PROJ-3"])
    entries = session.scalars(select(WatchlistEntry).order_by(WatchlistEntry.position)).all()
    keys = [e.issue_key for e in entries]
    assert keys == ["PROJ-1", "PROJ-2", "PROJ-3"]
    positions = [e.position for e in entries]
    assert positions == sorted(positions)


def test_add_reports_uncached_keys(session: Session, load_fixture) -> None:
    # Seed one issue into the cache directly, then verify add reports which keys are missing.
    from tendril.jira.dto import normalize_issue
    from tendril.sync.pipeline import upsert_issue
    upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
    session.commit()

    _, uncached = add_to_watchlist(session, ["PROJ-1", "PROJ-999"])
    assert uncached == ["PROJ-999"]


def test_remove_deletes_only_the_named_keys(session: Session) -> None:
    add_to_watchlist(session, ["PROJ-1", "PROJ-2", "PROJ-3"])
    n = remove_from_watchlist(session, ["PROJ-2", "GONE-99"])
    assert n == 1
    remaining = {e.issue_key for e in session.scalars(select(WatchlistEntry)).all()}
    assert remaining == {"PROJ-1", "PROJ-3"}


def test_sync_project_paginates_past_first_page(
    session: Session, load_fixture, fake_jira_class
) -> None:
    """Regression: JIRA Cloud's enhanced_jql uses token pagination, not startAt/total."""
    template = load_fixture("issue_sample.json")
    issues = {}
    for i in range(1, 121):  # 120 issues -> 3 pages at limit=50
        key = f"BIG-{i}"
        issues[key] = {**template, "key": key}
    client = fake_jira_class(issues)

    rows = sync_project(client, session, "BIG")
    assert len(rows) == 120
    assert len(client.jql_calls) == 3  # 50 + 50 + 20


def test_sync_project_pulls_all_matching_issues_and_stamps_state(
    session: Session, load_fixture, fake_jira_class
) -> None:
    client = fake_jira_class({
        "PROJ-1": load_fixture("issue_sample.json"),
        "PROJ-2": load_fixture("issue_second.json"),
    })

    rows = sync_project(client, session, "PROJ")
    assert {r.key for r in rows} == {"PROJ-1", "PROJ-2"}
    assert client.jql_calls, "expected a JQL call"
    assert 'project = "PROJ"' in client.jql_calls[0]

    state = session.get(ProjectSyncState, "PROJ")
    assert state is not None
    assert state.last_full_sync_at is not None
    assert state.last_incremental_sync_at is not None


def test_sync_project_ignores_issues_from_other_projects(
    session: Session, load_fixture, fake_jira_class
) -> None:
    other_issue = load_fixture("issue_sample.json")
    other_issue = {**other_issue, "key": "OTHER-9"}
    client = fake_jira_class({
        "PROJ-1": load_fixture("issue_sample.json"),
        "OTHER-9": other_issue,
    })
    rows = sync_project(client, session, "PROJ")
    assert {r.key for r in rows} == {"PROJ-1"}


def test_list_watchlist_pairs_entries_with_cached_issues(
    session: Session, load_fixture, fake_jira_class
) -> None:
    client = fake_jira_class({
        "PROJ-1": load_fixture("issue_sample.json"),
        # PROJ-2 intentionally not in JIRA fixtures -> stays un-synced
    })
    sync_project(client, session, "PROJ")
    add_to_watchlist(session, ["PROJ-1", "PROJ-2"])

    pairs = list_watchlist(session)
    keys_seen = {entry.issue_key: (issue is not None) for entry, issue in pairs}
    assert keys_seen == {"PROJ-1": True, "PROJ-2": False}


def test_incremental_with_no_synced_projects_is_a_noop(session: Session, fake_jira_class) -> None:
    client = fake_jira_class({})
    rows = incremental_sync(client, session)
    assert rows == []
    assert client.jql_calls == []


def test_incremental_uses_updated_clause_per_project(
    session: Session, load_fixture, fake_jira_class
) -> None:
    client = fake_jira_class({
        "PROJ-1": load_fixture("issue_sample.json"),
        "PROJ-2": load_fixture("issue_second.json"),
    })
    sync_project(client, session, "PROJ")
    # Nudge the timestamp backwards so an incremental JQL clause fires.
    state = session.get(ProjectSyncState, "PROJ")
    assert state is not None
    state.last_incremental_sync_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.commit()
    client.jql_calls.clear()

    incremental_sync(client, session)
    assert any('project = "PROJ"' in q and 'updated >=' in q for q in client.jql_calls)


def test_sync_issue_migrates_watchlist_on_jira_rename(
    session: Session, load_fixture, fake_jira_class
) -> None:
    """When JIRA moves an issue to another project, the watchlist entry follows."""
    from tendril.db.models import WatchlistEntry
    from tendril.sync.commands import sync_issue

    # JIRA now returns the moved issue under the new key, but a lookup by the old key
    # still resolves (JIRA follows internal redirects). Model this by mapping OLD -> renamed payload.
    renamed = {**load_fixture("issue_sample.json"), "key": "MOVED-42"}
    client = fake_jira_class({"OLD-1": renamed, "MOVED-42": renamed})
    add_to_watchlist(session, ["OLD-1"])

    sync_issue(client, session, "OLD-1")

    assert session.get(WatchlistEntry, "OLD-1") is None
    migrated = session.get(WatchlistEntry, "MOVED-42")
    assert migrated is not None


def test_incremental_falls_back_to_full_sync_if_no_timestamp(
    session: Session, load_fixture, fake_jira_class
) -> None:
    # Manually create a ProjectSyncState with no timestamps to simulate the fallback path.
    session.add(ProjectSyncState(project_key="PROJ"))
    session.commit()

    client = fake_jira_class({
        "PROJ-1": load_fixture("issue_sample.json"),
        "PROJ-2": load_fixture("issue_second.json"),
    })
    rows = incremental_sync(client, session)
    assert {r.key for r in rows} == {"PROJ-1", "PROJ-2"}
    assert any('updated >=' not in q and 'project = "PROJ"' in q for q in client.jql_calls)
