from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tendril.sync.commands import list_sprint_issues
from tendril.text import plural


class SprintWatchlistScreen(Screen):
    """Read-only view of every cached issue sitting in an active sprint.

    Populated dynamically from the cache — no manual add/remove.
    """

    BINDINGS = [
        Binding("s", "sync", "Sync incremental"),
        Binding("r", "refresh", "Reload"),
        Binding("escape", "pop", "Back"),
        Binding("q", "pop", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(id="sprint-table", cursor_type="row", zebra_stripes=True)
        yield Static("Loading…", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("key", width=15)
        table.add_column("status", width=20)
        table.add_column("summary", width=self.size.width - 100, key="summary")
        table.add_column("sprint", width=25)
        table.add_column("updated", width=20)
        self.reload()

    def on_resize(self) -> None:
        table = self.query_one(DataTable)
        table.columns["summary"].width = self.size.width - 100

    def reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()

        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            pairs = list_sprint_issues(session)
            for issue, sprint in pairs:
                updated = (
                    issue.updated.strftime("%Y-%m-%d %H:%M") if issue.updated else "—"
                )
                table.add_row(
                    Text(issue.key),
                    Text(issue.status or "—"),
                    Text((issue.summary or "").strip() or "—"),
                    Text(sprint.name),
                    Text(updated),
                    key=f"{issue.key}:{sprint.id}",
                )

        if not pairs:
            self._set_status(
                "No issues in an active sprint yet — run `tendril sync project KEY` first, "
                "and make sure `[fields].sprint` is set in config.toml."
            )
        else:
            self._set_status(f"{plural(len(pairs), 'issue')} in an active sprint.")

    def _set_status(self, text: str) -> None:
        self.query_one("#status-line", Static).update(text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        raw = str(event.row_key.value) if event.row_key.value is not None else ""
        key = raw.split(":", 1)[0]
        if key:
            self.app.push_screen(IssueDetailScreen(key))

    def action_sync(self) -> None:
        self.app.run_incremental_sync()  # type: ignore[attr-defined]

    def action_refresh(self) -> None:
        self.reload()

    def action_pop(self) -> None:
        self.app.pop_screen()
