from __future__ import annotations

import pytest
from sqlalchemy import select
from textual.widgets import DataTable, TabbedContent

from tendril.config import Config, JiraConfig
from tendril.db.engine import build_engine, session_factory
from tendril.db.models import Issue, IssueLink
from tendril.db.schema import init_schema
from tendril.jira.dto import normalize_issue
from tendril.sync.pipeline import upsert_issue
from tendril.tui.app import TendrilApp
from tendril.tui.screens.issue_detail import IssueDetailScreen


@pytest.fixture
def browser_app(isolated_xdg, load_fixture, monkeypatch):
    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as session:
        upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
        upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
        session.commit()
    engine.dispose()
    app = TendrilApp(Config(jira=JiraConfig(
        url="https://jira.example.test/jira/", email="me@example.test",
    )))
    opened: list[str] = []
    monkeypatch.setattr(app, "open_url", opened.append)
    return app, opened


@pytest.mark.parametrize("base_url", [
    "https://jira.example.test",
    "https://jira.example.test/",
    "https://jira.example.test/jira/",
])
async def test_open_current_issue_in_browser(browser_app, base_url) -> None:
    app, opened = browser_app
    app.cfg.jira.url = base_url
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-1"))
        await pilot.press("o")

        assert opened == [f"{base_url.rstrip('/')}/browse/PROJ-1"]
        assert app.screen.issue_key == "PROJ-1"


@pytest.mark.parametrize("target", ["PROJ-2", "PROJ-3"])
async def test_open_selected_link_in_browser(browser_app, target) -> None:
    """Both cached and uncached linked issues can be opened without navigating away."""
    app, opened = browser_app
    with app.session_factory() as session:
        link = session.scalar(select(IssueLink).where(
            IssueLink.source_key == "PROJ-1", IssueLink.target_key == target,
        ))
        assert link is not None
        row_key = f"link:{link.id}"
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-1"))
        app.screen.query_one(TabbedContent).active = "tab-links"
        await pilot.pause()
        table = app.screen.query_one("#links-table", DataTable)
        table.move_cursor(row=table.get_row_index(row_key))
        await pilot.press("o")

        assert opened == [f"https://jira.example.test/jira/browse/{target}"]
        assert app.screen.issue_key == "PROJ-1"
        # Enter retains its existing in-app navigation on the same row.
        table.focus()
        await pilot.press("enter")
        assert app.screen.issue_key == target


async def test_open_selected_child_in_browser(browser_app) -> None:
    app, opened = browser_app
    with app.session_factory() as session:
        child = session.get(Issue, "PROJ-1")
        assert child is not None
        child.parent_key = "PROJ-2"
        session.commit()
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-2"))
        app.screen.query_one(TabbedContent).active = "tab-links"
        await pilot.pause()
        table = app.screen.query_one("#links-table", DataTable)
        table.move_cursor(row=table.get_row_index("child:PROJ-1"))
        await pilot.press("o")

        assert opened == ["https://jira.example.test/jira/browse/PROJ-1"]
        assert app.screen.issue_key == "PROJ-2"


async def test_open_parent_in_browser_after_navigating_to_parent(browser_app) -> None:
    app, opened = browser_app
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-1"))
        await pilot.press("p", "o")

        assert opened == ["https://jira.example.test/jira/browse/PROJ-100"]
        assert app.screen.issue_key == "PROJ-100"


async def test_parent_navigation_is_unavailable_without_parent(browser_app) -> None:
    app, opened = browser_app
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-2"))
        await pilot.press("p")

        assert opened == []
        assert app.screen.check_action("open_parent", ()) is False


async def test_open_current_issue_when_links_table_is_empty(browser_app) -> None:
    app, opened = browser_app
    async with app.run_test() as pilot:
        await app.push_screen(IssueDetailScreen("PROJ-2"))
        app.screen.query_one(TabbedContent).active = "tab-links"
        await pilot.pause()
        table = app.screen.query_one("#links-table", DataTable)
        assert table.row_count == 0
        await pilot.press("o")

        assert opened == ["https://jira.example.test/jira/browse/PROJ-2"]
