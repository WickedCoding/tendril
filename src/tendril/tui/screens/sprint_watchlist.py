from __future__ import annotations

from rich.style import Style
from rich.text import Text
from sqlalchemy import select
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tendril.db.models import WatchlistEntry
from tendril.db.users import format_user, resolve_display_names
from tendril.sync.commands import (
    add_to_watchlist,
    list_sprint_issues,
    remove_from_watchlist,
)
from tendril.text import plural


class SprintWatchlistScreen(Screen):
    """Read-only view of every cached issue sitting in an active sprint.

    Populated dynamically from the cache; add/remove only toggles the watchlist
    marker on the highlighted issue — the sprint membership itself comes from JIRA.
    """

    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("d", "remove", "Remove"),
        Binding("s", "sync", "Sync incremental"),
        Binding("r", "refresh", "Reload"),
        Binding("m", "toggle_mine_filter", "Mine"),
        Binding("escape", "pop", "Back"),
        Binding("q", "pop", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._mine_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(id="sprint-table", cursor_type="row", zebra_stripes=True)
        yield Static("Loading…", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("★", width=1)
        table.add_column("key", width=15)
        table.add_column("status", width=20)
        table.add_column("summary", width=self.size.width - 120, key="summary")
        table.add_column("assignee", width=20)
        table.add_column("sprint", width=25)
        table.add_column("updated", width=20)
        self.reload()

    def on_resize(self) -> None:
        table = self.query_one(DataTable)
        table.columns["summary"].width = self.size.width - 120

    def reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        accent = self._accent_style()
        me = self._me()
        mine_active = self._mine_only and me is not None

        shown = 0
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            pairs = list_sprint_issues(session)
            names = resolve_display_names(
                session, (issue.assignee_account_id for issue, _ in pairs)
            )
            watchlisted = {
                key for (key,) in session.execute(select(WatchlistEntry.issue_key)).all()
            }
            for issue, sprint in pairs:
                if mine_active and issue.assignee_account_id != me:
                    continue
                is_watchlisted = issue.key in watchlisted
                style = accent if is_watchlisted else Style()
                marker = "★" if is_watchlisted else " "
                updated = (
                    issue.updated.strftime("%Y-%m-%d %H:%M") if issue.updated else "—"
                )
                table.add_row(
                    Text(marker, style=style),
                    Text(issue.key, style=style),
                    Text(issue.status or "—", style=style),
                    Text((issue.summary or "").strip() or "—", style=style),
                    Text(format_user(issue.assignee_account_id, names), style=style),
                    Text(sprint.name, style=style),
                    Text(updated, style=style),
                    key=f"{issue.key}:{sprint.id}",
                )
                shown += 1

        total = len(pairs)
        if not pairs:
            self._set_status(
                "No issues in an active sprint yet — run `tendril sync project KEY` first, "
                "and make sure `[fields].sprint` is set in config.toml."
            )
        else:
            self._set_status(self._status_text(shown, total))

    def _status_text(self, shown: int, total: int) -> str:
        filters = []
        if self._mine_only and self._me() is not None:
            filters.append("mine")
        suffix = f" · filters: {', '.join(filters)}" if filters else ""
        if self._mine_only and self._me() is None:
            suffix += ' · run `tendril whoami` to enable "mine"'
        if shown == total:
            return f"{plural(total, 'issue')} in an active sprint.{suffix}"
        return f"showing {shown} of {plural(total, 'issue')} in an active sprint.{suffix}"

    def _me(self) -> str | None:
        cfg = getattr(self.app, "cfg", None)
        return getattr(getattr(cfg, "jira", None), "account_id", None)

    def _accent_style(self) -> Style:
        theme = getattr(self.app, "current_theme", None)
        color = getattr(theme, "accent", None) or getattr(theme, "primary", None)
        if not color:
            return Style(color="cyan", bold=True)
        return Style(color=str(color), bold=True)

    def _set_status(self, text: str) -> None:
        self.query_one("#status-line", Static).update(text)

    def _cursor_issue_key(self) -> str | None:
        """Row keys are `"{issue_key}:{sprint_id}"`; strip the sprint suffix."""
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        raw = str(row_key.value) if row_key.value is not None else ""
        key = raw.split(":", 1)[0]
        return key or None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        raw = str(event.row_key.value) if event.row_key.value is not None else ""
        key = raw.split(":", 1)[0]
        if key:
            self.app.push_screen(IssueDetailScreen(key))

    def action_add(self) -> None:
        """Mark the highlighted sprint row's issue as watchlisted."""
        key = self._cursor_issue_key()
        if not key:
            return
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            add_to_watchlist(session, [key])
        self.reload()

    def action_remove(self) -> None:
        """Drop the highlighted sprint row's issue from the watchlist."""
        key = self._cursor_issue_key()
        if not key:
            return
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            remove_from_watchlist(session, [key])
        self.reload()

    def action_sync(self) -> None:
        self.app.run_incremental_sync()  # type: ignore[attr-defined]

    def action_refresh(self) -> None:
        self.reload()

    def action_toggle_mine_filter(self) -> None:
        self._mine_only = not self._mine_only
        self.reload()

    def action_pop(self) -> None:
        self.app.pop_screen()
