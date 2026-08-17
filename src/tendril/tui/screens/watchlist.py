from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tendril.sync.commands import add_to_watchlist, list_watchlist, remove_from_watchlist
from tendril.text import plural
from tendril.tui.screens.add_modal import AddToWatchlistModal


class WatchlistScreen(Screen):
    """DataTable of the curated watchlist. Read-only in v0 beyond add/remove locally."""

    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("d", "remove", "Remove"),
        Binding("s", "sync", "Sync incremental"),
        Binding("r", "refresh", "Reload"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(id="watchlist-table", cursor_type="row", zebra_stripes=True)
        yield Static("Loading…", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("key", "status", "summary", "assignee", "updated", "note")
        self.reload()

    def reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            pairs = list_watchlist(session)
            for entry, issue in pairs:
                table.add_row(
                    entry.issue_key,
                    (issue.status if issue else "—") or "—",
                    (issue.summary if issue else "[dim]not synced[/dim]") or "",
                    (issue.assignee_account_id if issue else "—") or "—",
                    (issue.updated.strftime("%Y-%m-%d %H:%M") if issue and issue.updated else "—"),
                    entry.note or "",
                    key=entry.issue_key,
                )
        self._set_status(f"{plural(len(pairs), 'entry', 'entries')} on watchlist.")

    def _set_status(self, text: str) -> None:
        self.query_one("#status-line", Static).update(text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        key = str(event.row_key.value) if event.row_key.value is not None else None
        if key:
            self.app.push_screen(IssueDetailScreen(key))

    def action_add(self) -> None:
        def _after(key: str | None) -> None:
            if not key:
                return
            with self.app.session_factory() as session:  # type: ignore[attr-defined]
                _, uncached = add_to_watchlist(session, [key])
            self.reload()
            if uncached:
                self._set_status(
                    f"Added {key}. Not in cache yet — sync the project or run `tendril sync issue {key}`."
                )

        self.app.push_screen(AddToWatchlistModal(), _after)

    def action_remove(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        key = str(row_key.value) if row_key.value is not None else None
        if not key:
            return
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            remove_from_watchlist(session, [key])
        self.reload()

    def action_sync(self) -> None:
        self.app.run_incremental_sync()  # type: ignore[attr-defined]

    def action_refresh(self) -> None:
        self.reload()

    def action_quit_app(self) -> None:
        self.app.exit()
