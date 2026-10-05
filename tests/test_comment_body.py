"""Comment bodies are kept as JIRA sent them and rendered at display time."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tendril.db.engine import build_engine
from tendril.db.models import Comment
from tendril.db.schema import _alembic_config
from tendril.jira.dto import normalize_issue
from tendril.sync.pipeline import upsert_issue
from tendril.tui.screens.issue_detail import _format_comments

LIST_ADF = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Steps:"}]},
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}],
                },
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}],
                },
            ],
        },
    ],
}


def test_sync_stores_raw_body_next_to_flattened_text(session: Session, load_fixture) -> None:
    upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
    session.commit()
    wiki = session.get(Comment, "30001")
    adf = session.get(Comment, "30002")
    assert wiki is not None and adf is not None
    assert wiki.body_raw == "Kicking this off."
    assert isinstance(adf.body_raw, dict) and adf.body_raw["type"] == "doc"
    assert adf.body == "Second comment in ADF."


def test_format_comments_renders_raw_body_and_falls_back_to_text() -> None:
    when = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    rendered = Comment(id="1", issue_key="P-1", body="Steps:onetwo", body_raw=LIST_ADF, created=when)
    legacy = Comment(id="2", issue_key="P-1", body="flattened only", body_raw=None, created=when)
    out = _format_comments([rendered, legacy], {}).plain
    assert "Steps:\n\n  • one\n  • two" in out
    assert "flattened only" in out
    assert "Steps:onetwo" not in out


def test_migration_0006_backfills_body_raw(tmp_path: Path, load_fixture) -> None:
    engine = build_engine(tmp_path / "m.db")
    cfg = _alembic_config()
    payload = load_fixture("issue_sample.json")
    payload["fields"]["comment"]["comments"][1]["body"] = LIST_ADF

    os.environ["TENDRIL_DB_URL"] = str(engine.url)
    try:
        command.upgrade(cfg, "0005")
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO issue (key, raw_json, last_synced_at, skills) "
                "VALUES (:k, :raw, '2026-10-05 07:00:00.000000', '[]')"
            ), {"k": payload["key"], "raw": json.dumps(payload)})
            for cid, body in (("30001", "Kicking this off."), ("30002", "Steps:onetwo"), ("gone", "old")):
                conn.execute(text(
                    "INSERT INTO comment (id, issue_key, body) VALUES (:id, :k, :b)"
                ), {"id": cid, "k": payload["key"], "b": body})

        command.upgrade(cfg, "head")
    finally:
        os.environ.pop("TENDRIL_DB_URL", None)

    with sessionmaker(bind=engine, future=True)() as s:
        wiki = s.get(Comment, "30001")
        adf = s.get(Comment, "30002")
        orphan = s.get(Comment, "gone")
        assert wiki is not None and adf is not None and orphan is not None
        assert wiki.body_raw == "Kicking this off."
        assert adf.body_raw == LIST_ADF
        assert orphan.body_raw is None
        assert orphan.body == "old"
