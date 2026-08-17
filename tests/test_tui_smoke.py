from __future__ import annotations

from pathlib import Path

import pytest

from tendril.config import Config, JiraConfig
from tendril.db.engine import build_engine, session_factory
from tendril.db.schema import init_schema
from tendril.jira.dto import normalize_issue
from tendril.sync.commands import add_to_watchlist
from tendril.sync.pipeline import upsert_issue
from tendril.tui.app import TendrilApp


def _seed(load_fixture) -> None:
    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as session:
        upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
        upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
        add_to_watchlist(session, ["PROJ-1", "PROJ-2"])


@pytest.mark.asyncio
async def test_watchlist_renders_seeded_entries(isolated_xdg: Path, load_fixture) -> None:
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        keys = {str(k.value) for k in table.rows.keys()}
        assert keys == {"PROJ-1", "PROJ-2"}


@pytest.mark.asyncio
async def test_open_issue_detail_and_back(isolated_xdg: Path, load_fixture) -> None:
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-1"

        await pilot.press("escape")
        await pilot.pause()
        from tendril.tui.screens.watchlist import WatchlistScreen
        assert isinstance(app.screen, WatchlistScreen)


@pytest.mark.asyncio
async def test_remove_from_watchlist_via_keybinding(isolated_xdg: Path, load_fixture) -> None:
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("d")
        await pilot.pause()
        assert table.row_count == 1
