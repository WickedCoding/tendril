from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SyncState(Base):
    """Singleton row; id is always 1. Holds schema version bookkeeping."""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


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
    sprint_name: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String, nullable=True)
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


class IssueAlert(Base):
    """Marker: this issue should surface as a card when another cached issue shares any of its tags."""

    __tablename__ = "issue_alert"

    issue_key: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
