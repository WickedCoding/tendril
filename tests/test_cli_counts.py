from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from tendril.cli import app
from tendril.db.engine import build_engine, session_factory
from tendril.db.models import WatchlistEntry


@pytest.mark.parametrize(
    ("existing", "added", "expected"),
    [
        ([], ["PROJ-1"], ["PROJ-1"]),
        (
            [f"PROJ-{i}" for i in range(1, 16)],
            ["PROJ-16", "PROJ-17"],
            [f"PROJ-{i}" for i in range(1, 18)],
        ),
        (["PROJ-1", "PROJ-2"], ["PROJ-2", "PROJ-3"], ["PROJ-1", "PROJ-2", "PROJ-3"]),
        (
            ["PROJ-1", "PROJ-2", "PROJ-3"],
            ["PROJ-1", "PROJ-1"],
            ["PROJ-1", "PROJ-2", "PROJ-3"],
        ),
    ],
    ids=["first-entry", "existing-fifteen", "mixed-existing-and-new", "duplicates-only"],
)
def test_watchlist_add_reports_persisted_total(isolated_xdg, existing, added, expected) -> None:
    runner = CliRunner()
    if existing:
        seed = runner.invoke(app, ["watchlist", "add", *existing])
        assert seed.exit_code == 0, seed.output

    result = runner.invoke(app, ["watchlist", "add", *added])

    assert result.exit_code == 0, result.output
    noun = "entry" if len(expected) == 1 else "entries"
    assert result.output.splitlines()[0] == f"Watchlist size: {len(expected)} {noun} after add."
    assert "Not yet in cache:" in result.output
    engine = build_engine()
    try:
        with session_factory(engine)() as session:
            keys = session.scalars(select(WatchlistEntry.issue_key)).all()
            assert sorted(keys) == sorted(expected)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("existing", "added", "expected"),
    [
        ([], ["alpha"], ["alpha"]),
        (["alpha", "beta"], ["gamma"], ["alpha", "beta", "gamma"]),
        (["alpha", "beta"], ["beta", "beta"], ["alpha", "beta"]),
    ],
    ids=["first-tag", "accumulated-tags", "duplicates-only"],
)
def test_tag_add_reports_complete_tag_set(isolated_xdg, existing, added, expected) -> None:
    runner = CliRunner()
    if existing:
        seed = runner.invoke(app, ["tag", "add", "PROJ-1", *existing])
        assert seed.exit_code == 0, seed.output

    result = runner.invoke(app, ["tag", "add", "PROJ-1", *added])

    assert result.exit_code == 0, result.output
    noun = "tag" if len(expected) == 1 else "tags"
    assert result.output.strip() == f"PROJ-1 now has {len(expected)} {noun}: {', '.join(expected)}"
    listed = runner.invoke(app, ["tag", "list", "PROJ-1", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output) == {"PROJ-1": expected}
