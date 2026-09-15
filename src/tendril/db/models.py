from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Float, Index, JSON, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectSyncState(Base):
    """Per-project last-sync bookkeeping. A row exists once a project has been synced at least once."""

    __tablename__ = "project_sync_state"

    project_key: Mapped[str] = mapped_column(String, primary_key=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_incremental_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "user"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)


class Issue(Base):
    __tablename__ = "issue"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    issuetype: Mapped[str | None] = mapped_column(String, nullable=True)
    assignee_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reporter_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duedate: Mapped[date | None] = mapped_column(Date, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String, nullable=True)
    story_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class IssueLink(Base):
    __tablename__ = "issue_link"
    __table_args__ = (
        UniqueConstraint(
            "source_key", "target_key", "link_type", "direction",
            name="uq_issue_link",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    link_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # "outward" | "inward"
    jira_link_id: Mapped[str] = mapped_column(String, nullable=False)


class Comment(Base):
    __tablename__ = "comment"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # JIRA comment id
    issue_key: Mapped[str] = mapped_column(String, nullable=False)
    author_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entry"

    issue_key: Mapped[str] = mapped_column(String, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IssueTag(Base):
    """Local, free-form label on a cached issue. Never pushed to JIRA."""

    __tablename__ = "issue_tag"

    issue_key: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)


class Sprint(Base):
    """One JIRA sprint. The PK is JIRA's global sprint id.

    State transitions (`future` → `active` → `closed`) happen JIRA-side; every
    upsert refreshes all mutable fields so the cache tracks the current state.
    """

    __tablename__ = "sprint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    board_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    complete_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IssueSprint(Base):
    """Join between issue and sprint. Replaced wholesale on each issue upsert."""

    __tablename__ = "issue_sprint"
    __table_args__ = (
        Index("ix_issue_sprint_sprint_id", "sprint_id"),
    )

    issue_key: Mapped[str] = mapped_column(String, primary_key=True)
    sprint_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class LinkType(Base):
    """A JIRA issue-link type as offered by the configured instance.

    Populated wholesale by `tendril sync link-types`; consumed by the link modals
    to offer a real chooser instead of a free-text field. `name` is what JIRA's
    create-link endpoint expects; `outward` and `inward` are the directional
    phrases humans read (e.g. name="Blocks", outward="blocks", inward="is blocked by").
    """

    __tablename__ = "link_type"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    outward: Mapped[str] = mapped_column(String, nullable=False)
    inward: Mapped[str] = mapped_column(String, nullable=False)


# Rollover step labels — stored as strings in RolloverAttempt.completed_step so
# the schema doesn't need to know about the enum. Ordering matters: each step
# must complete before the next begins. `rank_issues` sits right after the move
# so the JIRA sprint's display order matches the preview even if a later step
# fails and the rollover has to be resumed.
ROLLOVER_STEP_MOVE = "move_issues"
ROLLOVER_STEP_RANK = "rank_issues"
ROLLOVER_STEP_CLOSE = "close_source"
ROLLOVER_STEP_START = "start_target"
ROLLOVER_STEPS_ORDER: tuple[str, ...] = (
    ROLLOVER_STEP_MOVE,
    ROLLOVER_STEP_RANK,
    ROLLOVER_STEP_CLOSE,
    ROLLOVER_STEP_START,
)


class RolloverAttempt(Base):
    """In-flight or failed rollover state. One row per source sprint.

    Deleted on success; a lingering row on re-entry signals a partial rollover
    that the user can resume from `completed_step + 1`. `moved_issue_keys` tracks
    partial completion inside the move step (multiple JIRA calls, one per batch).
    """

    __tablename__ = "rollover_attempt"

    source_sprint_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_sprint_id: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_issue_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    moved_issue_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Final desired display order for the entire target sprint (carry-overs +
    # pre-existing issues, in the sequence the user arranged in the preview).
    # Pushed to JIRA in the `rank_issues` step.
    target_order_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    completed_step: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RolloverLog(Base):
    """Successful rollover history. Sprint names are denormalized so the log
    stays readable even if the sprint rows are later evicted from the cache.
    """

    __tablename__ = "rollover_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_sprint_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sprint_name: Mapped[str] = mapped_column(String, nullable=False)
    target_sprint_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_sprint_name: Mapped[str] = mapped_column(String, nullable=False)
    moved_issue_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    committed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
