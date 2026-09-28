from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from tendril.tags.ops import add_tags, list_tags_for
from tendril.config import Config
from tendril.db.models import (
    Comment, Issue, IssueLink, IssueSprint, IssueTag, LinkType, ProjectSyncState,
    Sprint, User, WatchlistEntry,
)
from tendril.jira.fetch import JiraLike, fetch_issue, fetch_link_types, search_by_jql
from tendril.sync.pipeline import upsert_issue

INCREMENTAL_SAFETY_BUFFER = timedelta(minutes=5)


def _extras_for_cfg(cfg: Config | None) -> list[str]:
    """Turn configured custom-field ids into the extra_fields list JIRA needs.

    Every configured field (`sprint`, `feature_flags`, `story_points`, `skills`)
    is opt-in per-instance; each is appended when set so project-sync payloads
    carry them into the cache — otherwise the detail view (and rollover screen)
    would render them empty even though JIRA has values.
    """
    if cfg is None:
        return []
    return [
        f for f in (
            cfg.fields.sprint,
            cfg.fields.feature_flags,
            cfg.fields.story_points,
            cfg.fields.skills,
        ) if f
    ]


def _sprint_field(cfg: Config | None) -> str | None:
    return cfg.fields.sprint if cfg is not None else None


def _story_points_field(cfg: Config | None) -> str | None:
    return cfg.fields.story_points if cfg is not None else None


def _skills_field(cfg: Config | None) -> str | None:
    return cfg.fields.skills if cfg is not None else None


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
    dto = fetch_issue(
        client, key,
        extra_fields=_extras_for_cfg(cfg),
        sprint_field_id=_sprint_field(cfg),
        story_points_field_id=_story_points_field(cfg),
        skills_field_id=_skills_field(cfg),
    )
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
    sprint_id = _sprint_field(cfg)
    sp_id = _story_points_field(cfg)
    skills_id = _skills_field(cfg)
    dtos = search_by_jql(
        client, f'project = "{project_key}"',
        extra_fields=extras,
        sprint_field_id=sprint_id,
        story_points_field_id=sp_id,
        skills_field_id=skills_id,
    )
    rows = [upsert_issue(session, dto) for dto in dtos]
    _touch_project_state(session, project_key, full=now, incremental=now)
    session.commit()
    return rows


def drop_project(session: Session, project_key: str) -> int:
    """Purge every cached row that belongs to `project_key`.

    Removes issues, their comments, issue-link rows on either side, sprint join
    rows, and the `ProjectSyncState`. Watchlist entries, local tags, sprint
    metadata rows, and rollover history are user data / cross-project state and
    are left alone; a re-sync repopulates the cache without touching them.

    Returns the number of `Issue` rows removed.
    """
    key_like = f"{project_key}-%"
    issue_count = session.scalar(
        select(func.count()).select_from(Issue).where(Issue.key.like(key_like))
    ) or 0

    session.execute(delete(Comment).where(Comment.issue_key.like(key_like)))
    session.execute(delete(IssueSprint).where(IssueSprint.issue_key.like(key_like)))
    session.execute(delete(IssueLink).where(
        or_(IssueLink.source_key.like(key_like), IssueLink.target_key.like(key_like))
    ))
    session.execute(delete(Issue).where(Issue.key.like(key_like)))
    session.execute(delete(ProjectSyncState).where(ProjectSyncState.project_key == project_key))

    session.commit()
    return int(issue_count)


def incremental_sync(
    client: JiraLike,
    session: Session,
    cfg: Config | None = None,
) -> list[Issue]:
    """Refetch issues updated since the last incremental sync, per project we've synced before.

    A project is only considered if `project sync` has run for it at least once.
    Updates each project's `last_incremental_sync_at` on success.
    """
    project_states = list(session.scalars(select(ProjectSyncState)).all())
    if not project_states:
        return []

    now = datetime.now(timezone.utc)
    extras = _extras_for_cfg(cfg)
    sprint_id = _sprint_field(cfg)
    sp_id = _story_points_field(cfg)
    skills_id = _skills_field(cfg)
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
        dtos = search_by_jql(
            client, jql,
            extra_fields=extras,
            sprint_field_id=sprint_id,
            story_points_field_id=sp_id,
            skills_field_id=skills_id,
        )
        all_rows.extend(upsert_issue(session, dto) for dto in dtos)
        state.last_incremental_sync_at = now

    session.commit()
    return all_rows


def sync_link_types(client: JiraLike, session: Session) -> list[LinkType]:
    """Replace the local link-type table with the current JIRA offering.

    Link types change rarely and only through admin action, so no incremental
    path: each call fetches the full list and overwrites the table.
    """
    fresh = fetch_link_types(client)
    session.query(LinkType).delete()
    rows = [LinkType(name=dto.name, outward=dto.outward, inward=dto.inward) for dto in fresh]
    session.add_all(rows)
    session.commit()
    return rows


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
    tags: list[str] | None = None,
) -> tuple[list[WatchlistEntry], list[str]]:
    """Add keys to the watchlist. Idempotent.

    Returns (entries, uncached_keys). `uncached_keys` are keys the caller may
    want to `sync issue KEY` — the watchlist itself does not fetch.

    `tags` are applied to every key via `tags.ops.add_tags` (idempotent per
    (key, tag)). Tag rows live on the issue, not the watchlist entry, so they
    survive removing and re-adding a key.
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
    if tags:
        for key in keys:
            add_tags(session, key, tags)
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


def list_watchlist(
    session: Session,
) -> list[tuple[WatchlistEntry, Issue | None, list[str]]]:
    """Return watchlist entries (in user-defined order) paired with their cached Issue and tags."""
    entries = list(session.scalars(
        select(WatchlistEntry).order_by(WatchlistEntry.position, WatchlistEntry.added_at)
    ).all())
    result: list[tuple[WatchlistEntry, Issue | None, list[str]]] = []
    for entry in entries:
        issue = session.get(Issue, entry.issue_key)
        result.append((entry, issue, list_tags_for(session, entry.issue_key)))
    return result


def list_sprint_issues(session: Session) -> list[tuple[Issue, Sprint]]:
    """Every cached issue that sits in any active sprint.

    Returns `(issue, sprint)` pairs so callers can render the sprint name as a
    column. An issue in more than one active sprint yields one row per sprint.
    """
    stmt = (
        select(Issue, Sprint)
        .join(IssueSprint, IssueSprint.issue_key == Issue.key)
        .join(Sprint, Sprint.id == IssueSprint.sprint_id)
        .where(Sprint.state == "active")
    )
    rows = list(session.execute(stmt).all())
    rows.sort(
        key=lambda r: (r[0].updated is None, -(r[0].updated.timestamp() if r[0].updated else 0))
    )
    return [(issue, sprint) for issue, sprint in rows]


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
    """Return cached issues matching `query` (case-insensitive).

    Prefix `#` narrows the search to tags only (e.g. `#logo`). Otherwise matches
    against key, tag, or summary and ranks: exact key > key startswith >
    key contains > exact tag > tag contains > summary contains.

    Ties broken by `updated` desc so recent work floats up. Empty/whitespace → [].
    """
    raw = query.strip().lower()
    if not raw:
        return []

    tag_only = raw.startswith("#")
    q = raw[1:] if tag_only else raw
    if not q:
        return []
    pattern = f"%{q}%"

    tag_stmt = select(IssueTag.issue_key, func.lower(IssueTag.tag)).where(
        func.lower(IssueTag.tag).like(pattern)
    )
    tag_matches: dict[str, set[str]] = {}
    for issue_key, tag in session.execute(tag_stmt).all():
        tag_matches.setdefault(issue_key, set()).add(tag)

    if tag_only:
        stmt = select(Issue).where(Issue.key.in_(tag_matches.keys()))
    else:
        stmt = select(Issue).where(
            or_(
                func.lower(Issue.key).like(pattern),
                func.lower(Issue.summary).like(pattern),
                Issue.key.in_(tag_matches.keys()),
            )
        )
    issues = list(session.scalars(stmt).all())

    def score(issue: Issue) -> int:
        tags = tag_matches.get(issue.key, set())
        if tag_only:
            return 0 if q in tags else 1
        key = (issue.key or "").lower()
        if key == q:
            return 0
        if key.startswith(q):
            return 1
        if q in key:
            return 2
        if q in tags:
            return 3
        if tags:
            return 4
        return 5

    issues.sort(
        key=lambda i: (
            score(i),
            i.updated is None,
            -(i.updated.timestamp() if i.updated else 0),
        )
    )
    return issues[:limit]


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_issues(
    session: Session,
    *,
    statuses: list[str] | None = None,
    projects: list[str] | None = None,
    assignee: str | None = None,
    sprint: str | None = None,
    tags: list[str] | None = None,
) -> list[Issue]:
    """Return cached issues matching every given filter, newest updated first.

    Values inside one list are OR'd; different filters are AND'd. Every
    comparison is exact but case-insensitive. `projects` match on the key
    prefix (`PROJ-`), `assignee` on the user's display name, `sprint` on the
    sprint name (any state). Raises `ValueError` when no filter is given.
    """
    statuses = [s.lower() for s in statuses or []]
    projects = [p.lower() for p in projects or []]
    tags = [t.lower() for t in tags or []]
    if not (statuses or projects or assignee or sprint or tags):
        raise ValueError("At least one filter is required.")

    stmt = select(Issue)
    if statuses:
        stmt = stmt.where(func.lower(Issue.status).in_(statuses))
    if projects:
        stmt = stmt.where(or_(*(
            func.lower(Issue.key).like(f"{_like_escape(p)}-%", escape="\\") for p in projects
        )))
    if assignee:
        stmt = stmt.where(Issue.assignee_account_id.in_(
            select(User.account_id).where(func.lower(User.display_name) == assignee.lower())
        ))
    if sprint:
        stmt = stmt.where(Issue.key.in_(
            select(IssueSprint.issue_key)
            .join(Sprint, Sprint.id == IssueSprint.sprint_id)
            .where(func.lower(Sprint.name) == sprint.lower())
        ))
    if tags:
        stmt = stmt.where(Issue.key.in_(
            select(IssueTag.issue_key).where(func.lower(IssueTag.tag).in_(tags))
        ))

    issues = list(session.scalars(stmt).all())
    issues.sort(key=lambda i: (i.updated is None, -(i.updated.timestamp() if i.updated else 0)))
    return issues


def sprint_names_for(session: Session, keys: list[str]) -> dict[str, list[str]]:
    """Return `{issue_key: [sprint names]}` for the given keys, in one query."""
    out: dict[str, list[str]] = {}
    if not keys:
        return out
    stmt = (
        select(IssueSprint.issue_key, Sprint.name)
        .join(Sprint, Sprint.id == IssueSprint.sprint_id)
        .where(IssueSprint.issue_key.in_(keys))
        .order_by(Sprint.id)
    )
    for key, name in session.execute(stmt).all():
        out.setdefault(key, []).append(name)
    return out
