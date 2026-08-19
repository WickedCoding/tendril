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
async def test_overview_renders_every_cached_issue(isolated_xdg: Path, load_fixture) -> None:
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
        _cursor_to_key(table, "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-1"

        await pilot.press("escape")
        await pilot.pause()
        from tendril.tui.screens.watchlist import WatchlistScreen
        assert isinstance(app.screen, WatchlistScreen)


def _cursor_to_key(table, key: str) -> None:
    """Move a DataTable's cursor onto the row with the given row-key."""
    for i, k in enumerate(table.rows.keys()):
        if str(k.value) == key:
            table.move_cursor(row=i)
            return
    raise AssertionError(f"row {key} not found in table")


@pytest.mark.asyncio
async def test_slash_opens_search_and_enter_jumps_to_issue(
    isolated_xdg: Path, load_fixture
) -> None:
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("slash")
        await pilot.pause()

        from tendril.tui.screens.search_modal import SearchModal
        assert isinstance(app.screen, SearchModal)

        # Type a key fragment; the input's on_input_changed populates the list.
        for ch in "proj-2":
            await pilot.press(ch if ch != "-" else "minus")
        await pilot.pause()

        from textual.widgets import OptionList
        results = app.screen.query_one(OptionList)
        assert results.option_count >= 1
        assert results.get_option_at_index(0).id == "PROJ-2"

        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-2"


@pytest.mark.asyncio
async def test_search_works_from_issue_detail_screen(
    isolated_xdg: Path, load_fixture
) -> None:
    """The `/` binding is app-level, so it must fire on IssueDetailScreen too."""
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-1"

        await pilot.press("slash")
        await pilot.pause()

        from tendril.tui.screens.search_modal import SearchModal
        assert isinstance(app.screen, SearchModal)


@pytest.mark.asyncio
async def test_remove_from_watchlist_via_keybinding(isolated_xdg: Path, load_fixture) -> None:
    """Pressing `d` drops the watchlist marker; the cached row itself stays."""
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-1")
        removed_key = "PROJ-1"

        await pilot.press("d")
        await pilot.pause()

        # Row stays — this is the overview, not a filtered watchlist view.
        assert table.row_count == 2
        # But the watchlist entry is gone.
        from tendril.db.models import WatchlistEntry
        with app.session_factory() as session:
            assert session.get(WatchlistEntry, removed_key) is None


@pytest.mark.asyncio
async def test_watchlist_filter_hides_non_watchlisted_rows(
    isolated_xdg: Path, load_fixture
) -> None:
    """Only PROJ-1 is on the watchlist; toggling `w` should hide PROJ-2."""
    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as session:
        from tendril.jira.dto import normalize_issue
        upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
        upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
        add_to_watchlist(session, ["PROJ-1"])

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2

        await pilot.press("w")
        await pilot.pause()
        assert table.row_count == 1
        assert str(next(iter(table.rows.keys())).value) == "PROJ-1"

        await pilot.press("w")
        await pilot.pause()
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_open_filter_hides_done_statuses(
    isolated_xdg: Path, load_fixture
) -> None:
    """`o` hides issues whose status is in the configured done_statuses list."""
    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as session:
        from tendril.db.models import Issue
        from tendril.jira.dto import normalize_issue
        upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
        upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
        # Force PROJ-2 into a done state so the filter can bite.
        proj2 = session.get(Issue, "PROJ-2")
        assert proj2 is not None
        proj2.status = "Closed"
        session.commit()

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2

        await pilot.press("o")
        await pilot.pause()
        assert table.row_count == 1
        assert str(next(iter(table.rows.keys())).value) == "PROJ-1"


@pytest.mark.asyncio
async def test_issue_detail_child_navigation_and_parent(
    isolated_xdg: Path, load_fixture
) -> None:
    """Children appear in the Links tab, selecting one drills in, and `p` walks back."""
    _seed(load_fixture)

    # Reparent PROJ-1 under PROJ-2 so PROJ-2 shows PROJ-1 as a child in the Links tab,
    # and PROJ-1's `p` binding walks back to PROJ-2.
    engine = build_engine()
    init_schema(engine)
    from tendril.db.models import Issue
    with session_factory(engine)() as s:
        proj1 = s.get(Issue, "PROJ-1")
        assert proj1 is not None
        proj1.parent_key = "PROJ-2"
        s.commit()

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, TabbedContent
        table = app.screen.query_one(DataTable)
        # Open PROJ-2 (the parent).
        for i, k in enumerate(table.rows.keys()):
            if str(k.value) == "PROJ-2":
                table.move_cursor(row=i)
                break
        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-2"

        # Switch to Links tab; PROJ-1 must be there as a Child row.
        tabs = app.screen.query_one(TabbedContent)
        tabs.active = "tab-links"
        await pilot.pause()

        links_table = app.screen.query_one("#links-table", DataTable)
        row_keys = {str(k.value) for k in links_table.rows.keys()}
        assert "child:PROJ-1" in row_keys

        # Selecting the child row opens PROJ-1.
        for i, k in enumerate(links_table.rows.keys()):
            if str(k.value) == "child:PROJ-1":
                links_table.move_cursor(row=i)
                break
        links_table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-1"

        # `p` walks back to PROJ-2.
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, IssueDetailScreen)
        assert app.screen.issue_key == "PROJ-2"

        # PROJ-2 has no parent — `p` must be hidden.
        assert app.screen.check_action("open_parent", ()) is False


@pytest.mark.asyncio
async def test_surface_card_renders_for_shared_tag(
    isolated_xdg: Path, load_fixture
) -> None:
    """A tagged alert issue surfaces as a card when the viewed issue shares a tag."""
    _seed(load_fixture)

    engine = build_engine()
    init_schema(engine)
    from tendril.alerts import ops as alert_ops

    with session_factory(engine)() as s:
        alert_ops.add_tags(s, "PROJ-1", ["logo"])
        alert_ops.add_tags(s, "PROJ-2", ["logo"])
        alert_ops.mark_alert(s, "PROJ-1")

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, OptionList, Static
        table = app.screen.query_one(DataTable)
        # Open PROJ-2 — PROJ-1 (the alert) should surface via shared "logo" tag.
        for i, k in enumerate(table.rows.keys()):
            if str(k.value) == "PROJ-2":
                table.move_cursor(row=i)
                break
        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)

        option_list = app.screen.query_one("#surfaces-list", OptionList)
        empty = app.screen.query_one("#surfaces-empty", Static)
        assert option_list.option_count == 1
        assert option_list.display is True
        assert empty.display is False


@pytest.mark.asyncio
async def test_surfaces_panel_shows_empty_state_without_matches(
    isolated_xdg: Path, load_fixture
) -> None:
    _seed(load_fixture)

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, OptionList, Static
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()

        option_list = app.screen.query_one("#surfaces-list", OptionList)
        empty = app.screen.query_one("#surfaces-empty", Static)
        assert option_list.option_count == 0
        assert option_list.display is False
        assert empty.display is True


@pytest.mark.asyncio
async def test_toggle_alert_binding_flips_marker(
    isolated_xdg: Path, load_fixture
) -> None:
    _seed(load_fixture)

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

        from tendril.alerts import ops as alert_ops
        engine = build_engine()
        init_schema(engine)
        with session_factory(engine)() as s:
            assert alert_ops.is_alert(s, "PROJ-1") is True

        await pilot.press("A")
        await pilot.pause()

        with session_factory(engine)() as s:
            assert alert_ops.is_alert(s, "PROJ-1") is False


@pytest.mark.asyncio
async def test_mine_filter_hides_rows_not_assigned_to_me_on_watchlist(
    isolated_xdg: Path, load_fixture
) -> None:
    """`m` narrows the overview to issues whose assignee matches `cfg.jira.account_id`.

    PROJ-1 is assigned to `acc-alice` in the fixture; PROJ-2 has a null assignee.
    """
    _seed(load_fixture)

    app = TendrilApp(
        Config(jira=JiraConfig(url="https://x", email="me@x", account_id="acc-alice"))
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2

        await pilot.press("m")
        await pilot.pause()
        assert table.row_count == 1
        assert str(next(iter(table.rows.keys())).value) == "PROJ-1"

        await pilot.press("m")
        await pilot.pause()
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_mine_filter_noop_without_account_id_on_watchlist(
    isolated_xdg: Path, load_fixture
) -> None:
    """Without `cfg.jira.account_id`, pressing `m` shows every row and hints at whoami."""
    _seed(load_fixture)

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, Static
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2

        await pilot.press("m")
        await pilot.pause()
        assert table.row_count == 2
        status = app.screen.query_one("#status-line", Static)
        assert "whoami" in str(status.render())


@pytest.mark.asyncio
async def test_mine_filter_hides_rows_not_assigned_to_me_on_sprint_watchlist(
    isolated_xdg: Path, load_fixture
) -> None:
    """`Shift+S` → sprint watchlist, `m` narrows the active-sprint list to my rows."""
    _seed(load_fixture)

    engine = build_engine()
    init_schema(engine)
    from tendril.db.models import IssueSprint, Sprint
    with session_factory(engine)() as s:
        s.add(Sprint(id=42, name="Sprint 42", state="active"))
        s.add(IssueSprint(issue_key="PROJ-1", sprint_id=42))
        s.add(IssueSprint(issue_key="PROJ-2", sprint_id=42))
        s.commit()

    app = TendrilApp(
        Config(jira=JiraConfig(url="https://x", email="me@x", account_id="acc-alice"))
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("S")
        await pilot.pause()

        from tendril.tui.screens.sprint_watchlist import SprintWatchlistScreen
        assert isinstance(app.screen, SprintWatchlistScreen)
        table = app.screen.query_one("#sprint-table")
        assert table.row_count == 2

        await pilot.press("m")
        await pilot.pause()
        assert table.row_count == 1
        assert str(next(iter(table.rows.keys())).value).startswith("PROJ-1:")

        await pilot.press("m")
        await pilot.pause()
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_mine_filter_hides_child_rows_in_issue_detail_links(
    isolated_xdg: Path, load_fixture
) -> None:
    """On the Links tab, `m` hides child rows whose assignee doesn't match me."""
    _seed(load_fixture)

    engine = build_engine()
    init_schema(engine)
    from tendril.db.models import Issue
    with session_factory(engine)() as s:
        # Reparent PROJ-1 (assignee acc-alice) under PROJ-2 (assignee null).
        proj1 = s.get(Issue, "PROJ-1")
        assert proj1 is not None
        proj1.parent_key = "PROJ-2"
        # A second, no-fixture child assigned to somebody else.
        from datetime import UTC, datetime
        s.add(
            Issue(
                key="PROJ-99",
                summary="stranger",
                status="Open",
                assignee_account_id="acc-bob",
                parent_key="PROJ-2",
                raw_json={},
                last_synced_at=datetime.now(UTC),
            )
        )
        s.commit()

    app = TendrilApp(
        Config(jira=JiraConfig(url="https://x", email="me@x", account_id="acc-alice"))
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, TabbedContent
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-2")
        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.issue_detail import IssueDetailScreen
        assert isinstance(app.screen, IssueDetailScreen)

        tabs = app.screen.query_one(TabbedContent)
        tabs.active = "tab-links"
        await pilot.pause()

        links = app.screen.query_one("#links-table", DataTable)
        row_keys = {str(k.value) for k in links.rows.keys()}
        assert "child:PROJ-1" in row_keys
        assert "child:PROJ-99" in row_keys

        await pilot.press("m")
        await pilot.pause()
        row_keys = {str(k.value) for k in links.rows.keys()}
        assert row_keys == {"child:PROJ-1"}


@pytest.mark.asyncio
async def test_watchlist_shows_assignee_display_name_not_account_id(
    isolated_xdg: Path, load_fixture
) -> None:
    """PROJ-1's assignee cell must render the cached User's display name."""
    _seed(load_fixture)

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        row = table.get_row("PROJ-1")
        # Column order: ★, key, status, summary, assignee, updated
        assignee_cell = str(row[4])
        assert "Alice Alignment" in assignee_cell
        assert "acc-alice" not in assignee_cell


@pytest.mark.asyncio
async def test_issue_detail_meta_shows_display_names(
    isolated_xdg: Path, load_fixture
) -> None:
    """Assignee and reporter in the meta line resolve to display names when cached."""
    _seed(load_fixture)

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable, Label
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()

        meta = str(app.screen.query_one("#meta-line-1", Label).render())
        assert "Alice Alignment" in meta
        assert "acc-alice" not in meta


@pytest.mark.asyncio
async def test_palette_lists_sync_commands(isolated_xdg: Path) -> None:
    """Command-palette provider yields the prompt entry plus one per synced project.

    Exercises the provider directly against an in-tmp DB so we don't need the
    full TendrilApp (which would try to launch the auto-sync worker).
    """
    from tendril.db.models import ProjectSyncState
    from tendril.tui.commands import SyncCommands

    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as s:
        s.add(ProjectSyncState(project_key="ZED"))
        s.commit()

    class _StubApp:
        session_factory = session_factory(engine)
        def run_project_sync(self, key): pass
        def push_screen(self, *a, **k): pass

    class _TestProvider(SyncCommands):
        @property
        def app(self):  # type: ignore[override]
            return _StubApp()

    provider = _TestProvider.__new__(_TestProvider)  # skip Provider.__init__ (needs a screen)

    labels = [hit.text async for hit in provider.discover()]
    assert "Sync project…" in labels
    assert "Sync project ZED" in labels


@pytest.mark.asyncio
async def test_add_to_watchlist_via_keybinding(isolated_xdg: Path, load_fixture) -> None:
    """Pressing `a` marks the highlighted issue as watchlisted — no modal, no cursor → no-op."""
    engine = build_engine()
    init_schema(engine)
    with session_factory(engine)() as session:
        upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
        upsert_issue(session, normalize_issue(load_fixture("issue_second.json")))
        # Only PROJ-1 pre-watchlisted; PROJ-2 is the one we'll add via `a`.
        add_to_watchlist(session, ["PROJ-1"])

    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable
        table = app.screen.query_one(DataTable)
        _cursor_to_key(table, "PROJ-2")

        await pilot.press("a")
        await pilot.pause()

        from tendril.db.models import WatchlistEntry
        with app.session_factory() as session:
            assert session.get(WatchlistEntry, "PROJ-2") is not None


@pytest.mark.asyncio
async def test_theme_change_persists_to_config(isolated_xdg: Path) -> None:
    from tendril import config as cfg_mod

    cfg = Config(jira=JiraConfig(url="https://x", email="me@x"))
    cfg_mod.save(cfg)
    app = TendrilApp(cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.theme = "nord"
        await pilot.pause()

    assert cfg_mod.load().ui.theme == "nord"


@pytest.mark.asyncio
async def test_theme_from_config_applied_on_mount(isolated_xdg: Path) -> None:
    from tendril import config as cfg_mod
    from tendril.config import UIConfig

    cfg_mod.save(
        Config(jira=JiraConfig(url="https://x", email="me@x"), ui=UIConfig(theme="nord"))
    )
    app = TendrilApp(cfg_mod.load())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "nord"
