from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tendril.db.users import format_user, resolve_display_names
from tendril.sync.commands import (
    add_to_watchlist,
    list_all_issues,
    remove_from_watchlist,
)
from tendril.text import plural
from tendril.tui.screens.add_modal import AddToWatchlistModal


class WatchlistScreen(Screen):
    """Overview of every cached issue with watchlist + open/closed filters."""

    BINDINGS = [
        Binding("/", "app.open_search", "Search"),
        Binding("a", "add", "Add"),
        Binding("d", "remove", "Remove"),
        Binding("w", "toggle_watchlist_filter", "Watchlist only"),
        Binding("o", "toggle_open_filter", "Open only"),
        Binding("m", "toggle_mine_filter", "Mine"),
        Binding("S", "app.open_sprint_watchlist", "Sprint"),
        Binding("s", "sync", "Sync incremental"),
        Binding("r", "refresh", "Reload"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._watchlist_only = False
        self._open_only = False
        self._mine_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(id="watchlist-table", cursor_type="row", zebra_stripes=True)
        yield Static("Loading…", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("★", width=1)
        table.add_column("key", width=15)
        table.add_column("status", width=20)
        table.add_column("summary", width=self.size.width - 100, key="summary")
        table.add_column("assignee", width=20)
        table.add_column("updated", width=20)
        self.reload()

    def on_resize(self) -> None:
        table = self.query_one(DataTable)
        table.columns["summary"].width = self.size.width - 100

    def reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        accent = self._accent_style()
        done = self._done_statuses()
        me = self._me()
        mine_active = self._mine_only and me is not None

        shown = 0
        total = 0
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            pairs = list_all_issues(session)
            names = resolve_display_names(
                session, (issue.assignee_account_id for issue, _ in pairs)
            )
            for issue, is_watchlisted in pairs:
                total += 1
                if self._watchlist_only and not is_watchlisted:
                    continue
                if self._open_only and (issue.status or "") in done:
                    continue
                if mine_active and issue.assignee_account_id != me:
                    continue

                style = accent if is_watchlisted else Style()
                marker = "★" if is_watchlisted else " "
                updated = (
                    issue.updated.strftime("%Y-%m-%d %H:%M") if issue.updated else "—"
                )
                cells = [
                    Text(marker, style=style),
                    Text(issue.key, style=style),
                    Text(issue.status or "—", style=style),
                    Text((issue.summary or "").strip() or "—", style=style),
                    Text(format_user(issue.assignee_account_id, names), style=style),
                    Text(updated, style=style),
                ]
                table.add_row(*cells, key=issue.key)
                shown += 1

        self._set_status(self._status_text(shown, total))

    def _status_text(self, shown: int, total: int) -> str:
        filters = []
        if self._watchlist_only:
            filters.append("watchlist")
        if self._open_only:
            filters.append("open")
        if self._mine_only and self._me() is not None:
            filters.append("mine")
        suffix = f" · filters: {', '.join(filters)}" if filters else ""
        if self._mine_only and self._me() is None:
            suffix += ' · run `tendril whoami` to enable "mine"'
        if shown == total:
            return f"{plural(total, 'cached issue')}.{suffix}"
        return f"showing {shown} of {plural(total, 'cached issue')}.{suffix}"

    def _me(self) -> str | None:
        cfg = getattr(self.app, "cfg", None)
        return getattr(getattr(cfg, "jira", None), "account_id", None)

    def _accent_style(self) -> Style:
        """Bold + the theme's accent color, so watchlisted rows pop in both themes."""
        theme = getattr(self.app, "current_theme", None)
        color = getattr(theme, "accent", None) or getattr(theme, "primary", None)
        if not color:
            return Style(color="cyan", bold=True)
        return Style(color=str(color), bold=True)

    def _done_statuses(self) -> set[str]:
        cfg = getattr(self.app, "cfg", None)
        if cfg is None:
            return set()
        return set(cfg.overview.done_statuses)

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

        self.app.push_screen(AddToWatchlistModal(prefill=self._cursor_key()), _after)

    def _cursor_key(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key.value is not None else None

    def action_remove(self) -> None:
        """Drop the highlighted issue from the watchlist (the cached issue stays)."""
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

    def action_toggle_watchlist_filter(self) -> None:
        self._watchlist_only = not self._watchlist_only
        self.reload()

    def action_toggle_open_filter(self) -> None:
        self._open_only = not self._open_only
        self.reload()

    def action_toggle_mine_filter(self) -> None:
        self._mine_only = not self._mine_only
        self.reload()

    def action_sync(self) -> None:
        self.app.run_incremental_sync()  # type: ignore[attr-defined]

    def action_refresh(self) -> None:
        self.reload()

    def action_quit_app(self) -> None:
        self.app.exit()
