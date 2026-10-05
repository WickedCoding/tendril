from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from tendril.db.models import Issue, LinkType, User


DESCRIPTION_ADF = {
    "type": "doc",
    "version": 1,
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Fix the login flow."}]},
    ],
}


def _seed(session: Session, load_fixture) -> None:
    """PROJ-1 blocks PROJ-2 (cached), is related from PROJ-3 (not cached), parents PROJ-2."""
    from tendril.jira.dto import normalize_issue
    from tendril.sync.pipeline import upsert_issue
    upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
    upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
    session.flush()

    session.merge(User(account_id="acc-alice", display_name="Alice Alignment"))
    session.merge(LinkType(name="Blocks", outward="blocks", inward="is blocked by"))
    p1 = session.get(Issue, "PROJ-1")
    p2 = session.get(Issue, "PROJ-2")
    assert p1 is not None and p2 is not None
    p1.raw_json = {**p1.raw_json, "fields": {**p1.raw_json["fields"], "description": DESCRIPTION_ADF}}
    p2.parent_key = "PROJ-1"
    session.commit()


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


def test_json_shape(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["show", "PROJ-1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["key"] == "PROJ-1"
    assert payload["project"] == "PROJ"
    assert payload["assignee"] == "Alice Alignment"
    assert payload["description"] == "Fix the login flow."
    assert payload["links"] == [
        {
            "key": "PROJ-2",
            "type": "Blocks",
            "direction": "outward",
            "phrase": "blocks",
            "summary": payload["links"][0]["summary"],
            "status": payload["links"][0]["status"],
            "cached": True,
        },
        {
            "key": "PROJ-3",
            "type": "Relates",
            "direction": "inward",
            "phrase": "Relates ←",
            "summary": None,
            "status": None,
            "cached": False,
        },
    ]
    assert payload["links"][0]["summary"] is not None
    assert [c["key"] for c in payload["children"]] == ["PROJ-2"]
    assert isinstance(payload["comment_count"], int)


def test_json_without_description_is_null(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["show", "PROJ-2", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["description"] is None
    assert payload["links"] == []
    assert payload["children"] == []


def test_text_output_has_description_and_links(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["show", "PROJ-1"])
    assert result.exit_code == 0, result.output
    assert "Fix the login flow." in result.output
    assert "Alice Alignment" in result.output
    assert "blocks" in result.output and "PROJ-2" in result.output
    assert "not synced" in result.output
    assert "contains" in result.output


def test_text_output_without_description(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["show", "PROJ-2"])
    assert result.exit_code == 0, result.output
    assert "no description" in result.output
    assert "Links" not in result.output


def test_unknown_key_exits_1(cli_db) -> None:
    from tendril.cli import app
    result = CliRunner().invoke(app, ["show", "NOPE-1", "--json"])
    assert result.exit_code == 1
