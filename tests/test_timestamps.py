"""JIRA timestamps carry an offset; the cache must store them as UTC.

The shared fixtures all use `+0000`, which hides an offset being dropped, so
these tests rewrite them to `+0200`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tendril.db.engine import build_engine
from tendril.db.models import Comment, Issue
from tendril.db.schema import _alembic_config
from tendril.jira.dto import normalize_issue
from tendril.sync.pipeline import upsert_issue
from tendril.text import local_time

UTC = timezone.utc


def _cest_payload(load_fixture) -> dict:
    payload = load_fixture("issue_sample.json")
    payload["fields"]["created"] = "2026-06-23T14:17:28.806+0200"
    payload["fields"]["updated"] = "2026-06-23T16:00:00.000+0200"
    payload["fields"]["comment"]["comments"][0]["created"] = "2026-06-23T09:30:00.000+0200"
    payload["fields"]["comment"]["comments"][0]["updated"] = "2026-06-23T09:45:00.000+0200"
    return payload


def test_offset_timestamps_are_stored_as_utc(tmp_path: Path, load_fixture) -> None:
    from tendril.db.schema import init_schema
    engine = build_engine(tmp_path / "t.db")
    init_schema(engine)
    Factory = sessionmaker(bind=engine, future=True)
    payload = _cest_payload(load_fixture)
    comment_id = payload["fields"]["comment"]["comments"][0]["id"]
    with Factory() as s:
        upsert_issue(s, normalize_issue(payload))
        s.commit()

    with Factory() as s:  # fresh session: values come back from SQLite, not the identity map
        issue = s.get(Issue, payload["key"])
        assert issue is not None
        assert issue.created == datetime(2026, 6, 23, 12, 17, 28, 806000, tzinfo=UTC)
        assert issue.updated == datetime(2026, 6, 23, 14, 0, tzinfo=UTC)
        assert issue.last_synced_at.tzinfo is UTC
        comment = s.get(Comment, comment_id)
        assert comment is not None
        assert comment.created == datetime(2026, 6, 23, 7, 30, tzinfo=UTC)

    raw = engine.connect().execute(
        text("SELECT updated FROM issue WHERE key = :k"), {"k": payload["key"]}
    ).scalar_one()
    assert raw.startswith("2026-06-23 14:00:00")


def test_winter_and_summer_offsets_sort_by_real_instant(session: Session, load_fixture) -> None:
    """01:30+0200 happened before 01:00+0100 — wall-clock storage got this backwards."""
    a = load_fixture("issue_sample.json")
    b = load_fixture("issue_second.json")
    a["fields"]["updated"] = "2026-10-25T01:30:00.000+0200"  # 23:30 UTC the day before
    b["fields"]["updated"] = "2026-10-25T01:00:00.000+0100"  # 00:00 UTC, half an hour later
    upsert_issue(session, normalize_issue(a))
    upsert_issue(session, normalize_issue(b))
    session.commit()
    session.expire_all()
    ia, ib = session.get(Issue, a["key"]), session.get(Issue, b["key"])
    assert ia is not None and ib is not None
    assert ia.updated < ib.updated


def test_local_time_renders_in_machine_timezone(monkeypatch) -> None:
    import time
    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    time.tzset()
    try:
        assert local_time(datetime(2026, 6, 23, 12, 17, tzinfo=UTC)) == "2026-06-23 14:17"
        assert local_time(None) == "—"
        assert local_time(None, missing="-") == "-"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_migration_0005_rewrites_wall_clock_rows_to_utc(tmp_path: Path, load_fixture) -> None:
    engine = build_engine(tmp_path / "m.db")
    cfg = _alembic_config()
    payload = _cest_payload(load_fixture)
    comment_id = payload["fields"]["comment"]["comments"][0]["id"]

    os.environ["TENDRIL_DB_URL"] = str(engine.url)
    try:
        command.upgrade(cfg, "0004")
        with engine.begin() as conn:
            # What the pre-0005 code wrote: JIRA wall-clock time, offset dropped.
            conn.execute(text(
                "INSERT INTO issue (key, raw_json, created, updated, last_synced_at, skills) "
                "VALUES (:k, :raw, '2026-06-23 14:17:28.806000', '2026-06-23 16:00:00.000000', "
                "'2026-09-28 07:00:00.000000', '[]')"
            ), {"k": payload["key"], "raw": json.dumps(payload)})
            conn.execute(text(
                "INSERT INTO comment (id, issue_key, body, created, updated) "
                "VALUES (:id, :k, 'x', '2026-06-23 09:30:00.000000', '2026-06-23 09:45:00.000000')"
            ), {"id": comment_id, "k": payload["key"]})
            conn.execute(text(
                "INSERT INTO comment (id, issue_key, body, created) "
                "VALUES ('gone', :k, 'deleted in JIRA', '2026-06-01 12:00:00.000000')"
            ), {"k": payload["key"]})

        command.upgrade(cfg, "head")
    finally:
        os.environ.pop("TENDRIL_DB_URL", None)

    with sessionmaker(bind=engine, future=True)() as s:
        issue = s.get(Issue, payload["key"])
        assert issue is not None
        assert issue.created == datetime(2026, 6, 23, 12, 17, 28, 806000, tzinfo=UTC)
        assert issue.updated == datetime(2026, 6, 23, 14, 0, tzinfo=UTC)
        # Already UTC before the migration; must be untouched.
        assert issue.last_synced_at == datetime(2026, 9, 28, 7, 0, tzinfo=UTC)
        comment = s.get(Comment, comment_id)
        assert comment is not None
        assert comment.created == datetime(2026, 6, 23, 7, 30, tzinfo=UTC)
        assert comment.updated == datetime(2026, 6, 23, 7, 45, tzinfo=UTC)
        orphan = s.get(Comment, "gone")
        assert orphan is not None
        assert orphan.created == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # left as-is
