from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tendril.config import Config
from tendril.db.models import Issue, ProjectSyncState, WatchlistEntry
from tendril.jira.fetch import JiraLike, fetch_issue, search_by_jql
from tendril.sync.pipeline import upsert_issue

INCREMENTAL_SAFETY_BUFFER = timedelta(minutes=5)


def _extras_for_cfg(cfg: Config | None) -> list[str]:
    """Turn configured custom-field ids into the extra_fields list JIRA needs.

    `cfg.fields.sprint` and `cfg.fields.feature_flags` are opt-in per-instance
    customfield ids. When set, they're appended so project-sync payloads carry
    them into the cache — otherwise the detail view would render them empty
    even though JIRA has values.
    """
    if cfg is None:
        return []
    return [f for f in (cfg.fields.sprint, cfg.fields.feature_flags) if f]


def sync_issue(
    client: JiraLike,
    session: Session,
    key: str,
    cfg: Config | None = None,
) -> Issue:
    """Fetch one issue from JIRA and upsert it into the cache.

    JIRA follows internal redirects when an issue has been moved between projects,
    so the returned key may differ from `key`. When that happens we migrate any
    watchlist entry from the old key to the new one so the watchlist stays live.
    """
    dto = fetch_issue(client, key, extra_fields=_extras_for_cfg(cfg))
    if dto.key != key:
        _migrate_watchlist_key(session, old=key, new=dto.key)
    row = upsert_issue(session, dto)
    session.commit()
    return row


def _migrate_watchlist_key(session: Session, *, old: str, new: str) -> None:
    entry = session.get(WatchlistEntry, old)
    if entry is None:
        return
    if session.get(WatchlistEntry, new) is not None:
        # New key already on the watchlist; drop the orphan old entry.
        session.delete(entry)
        return
    session.add(WatchlistEntry(
        issue_key=new,
        added_at=entry.added_at,
        note=entry.note,
        position=entry.position,
    ))
    session.delete(entry)
    session.flush()


def sync_project(
    client: JiraLike,
    session: Session,
    project_key: str,
    cfg: Config | None = None,
) -> list[Issue]:
    """Fetch every issue in a JIRA project and upsert into the cache.

    Paginated via `search_by_jql`. Stamps the project's `last_full_sync_at`
    so `incremental_sync` knows to include it next time.
    """
    now = datetime.now(timezone.utc)
    extras = _extras_for_cfg(cfg)
    dtos = search_by_jql(client, f'project = "{project_key}"', extra_fields=extras)
    rows = [upsert_issue(session, dto) for dto in dtos]
    _touch_project_state(session, project_key, full=now, incremental=now)
    session.commit()
    return rows


def incremental_sync(
    client: JiraLike,
    session: Session,
    cfg: Config | None = None,
) -> list[Issue]:
    """Refetch issues updated since the last incremental sync, per project we've synced before.

    A project is only considered if `sync project` has run for it at least once.
    Updates each project's `last_incremental_sync_at` on success.
    """
    project_states = list(session.scalars(select(ProjectSyncState)).all())
    if not project_states:
        return []

    now = datetime.now(timezone.utc)
    extras = _extras_for_cfg(cfg)
    all_rows: list[Issue] = []
    for state in project_states:
        since_source = state.last_incremental_sync_at or state.last_full_sync_at
        if since_source is None:
            # No timestamp anywhere — fall back to a full project sync.
            all_rows.extend(sync_project(client, session, state.project_key, cfg=cfg))
            continue
        since = since_source - INCREMENTAL_SAFETY_BUFFER
        jql = (
            f'project = "{state.project_key}" '
            f'AND updated >= "{since.strftime("%Y-%m-%d %H:%M")}"'
        )
        dtos = search_by_jql(client, jql, extra_fields=extras)
        all_rows.extend(upsert_issue(session, dto) for dto in dtos)
        state.last_incremental_sync_at = now

    session.commit()
    return all_rows


def _touch_project_state(
    session: Session,
    project_key: str,
    *,
    full: datetime | None = None,
    incremental: datetime | None = None,
) -> None:
    state = session.get(ProjectSyncState, project_key)
    if state is None:
        state = ProjectSyncState(project_key=project_key)
        session.add(state)
    if full is not None:
        state.last_full_sync_at = full
    if incremental is not None:
        state.last_incremental_sync_at = incremental


def add_to_watchlist(
    session: Session,
    keys: list[str],
    note: str | None = None,
) -> tuple[list[WatchlistEntry], list[str]]:
    """Add keys to the watchlist. Idempotent.

    Returns (entries, uncached_keys). `uncached_keys` are keys the caller may
    want to `sync issue KEY` — the watchlist itself does not fetch.
    """
    entries: list[WatchlistEntry] = []
    uncached: list[str] = []
    max_position = session.query(WatchlistEntry).count()
    for key in keys:
        existing = session.get(WatchlistEntry, key)
        if existing is not None:
            entries.append(existing)
        else:
            entry = WatchlistEntry(
                issue_key=key,
                added_at=datetime.now(timezone.utc),
                note=note,
                position=max_position,
            )
            session.add(entry)
            entries.append(entry)
            max_position += 1
        if session.get(Issue, key) is None:
            uncached.append(key)
    session.commit()
    return entries, uncached


def remove_from_watchlist(session: Session, keys: list[str]) -> int:
    """Remove keys from the watchlist. Returns the number of rows deleted."""
    deleted = 0
    for key in keys:
        entry = session.get(WatchlistEntry, key)
        if entry is not None:
            session.delete(entry)
            deleted += 1
    session.commit()
    return deleted


def list_watchlist(session: Session) -> list[tuple[WatchlistEntry, Issue | None]]:
    """Return watchlist entries (in user-defined order) paired with their cached Issue if present."""
    entries = list(session.scalars(
        select(WatchlistEntry).order_by(WatchlistEntry.position, WatchlistEntry.added_at)
    ).all())
    result: list[tuple[WatchlistEntry, Issue | None]] = []
    for entry in entries:
        issue = session.get(Issue, entry.issue_key)
        result.append((entry, issue))
    return result


def list_all_issues(session: Session) -> list[tuple[Issue, bool]]:
    """Return every cached issue paired with a watchlisted flag, newest updated first.

    Issues with no `updated` timestamp sort to the end so a stale/broken row
    doesn't push the freshest work off the top.
    """
    issues = list(session.scalars(select(Issue)).all())
    watchlisted = {
        key for (key,) in session.execute(select(WatchlistEntry.issue_key)).all()
    }
    issues.sort(key=lambda i: (i.updated is None, -(i.updated.timestamp() if i.updated else 0)))
    return [(issue, issue.key in watchlisted) for issue in issues]


def search_issues(session: Session, query: str, limit: int = 50) -> list[Issue]:
    """Return cached issues matching `query` (case-insensitive) against key or summary.

    Ranked: exact key > key startswith > key contains > summary contains.
    Ties broken by `updated` desc so recent work floats up. Empty/whitespace → [].
    """
    q = query.strip().lower()
    if not q:
        return []
    pattern = f"%{q}%"
    stmt = select(Issue).where(
        or_(
            func.lower(Issue.key).like(pattern),
            func.lower(Issue.summary).like(pattern),
        )
    )
    issues = list(session.scalars(stmt).all())

    def score(issue: Issue) -> int:
        key = (issue.key or "").lower()
        if key == q:
            return 0
        if key.startswith(q):
            return 1
        if q in key:
            return 2
        return 3

    issues.sort(
        key=lambda i: (
            score(i),
            i.updated is None,
            -(i.updated.timestamp() if i.updated else 0),
        )
    )
    return issues[:limit]
