from __future__ import annotations

from collections import deque
from typing import Any, Callable, Mapping

from textual.actions import ActionParseResult, parse as parse_action
from textual.app import App
from textual.command import CommandPalette
from textual.dom import DOMNode
from textual.screen import Screen
from textual.binding import Binding
from textual.worker import Worker

from tendril import config as config_mod
from tendril import feedback
from tendril.config import Config
from tendril.db.engine import build_engine, session_factory as make_session_factory
from tendril.db.schema import init_schema
from tendril.db.models import ProjectSyncState
from tendril.jira import client as jira_client
from tendril.sync.commands import incremental_sync, sync_issue, sync_project
from tendril.text import plural
from tendril.tui.commands import FeedbackCommands, SortCommands, SyncCommands
from tendril.tui.screens.feedback_modal import FeedbackModal
from tendril.tui.screens.watchlist import WatchlistScreen


def _defined_in_tendril(obj: object) -> bool:
    return getattr(obj, "__module__", "").startswith("tendril.")


class TendrilApp(App):
    """Textual app root. Holds the SQLAlchemy session factory and JIRA client."""

    TITLE = "tendril"
    COMMANDS = App.COMMANDS | {SyncCommands, SortCommands, FeedbackCommands}
    BINDINGS = [
        Binding("/", "open_search", "Search", show=False),
        Binding("S", "open_sprint_watchlist", "Sprint", show=False),
        Binding("R", "open_rollover_picker", "Rollover", show=False),
    ]

    def __init__(self, cfg: Config, update_available: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.update_available = update_available
        engine = build_engine()
        init_schema(engine)
        self.session_factory = make_session_factory(engine)
        self._jira = None  # lazy — do not hit keyring until needed
        # Feedback context. Action names only (never params) and the last
        # worker error; see tendril.feedback for what may leave the machine.
        self._recent_actions: deque[str] = deque(maxlen=10)
        self._last_error: BaseException | None = None

    def on_mount(self) -> None:
        if self.cfg.ui.theme:
            self.theme = self.cfg.ui.theme
        self.push_screen(WatchlistScreen())
        if self.update_available:
            from tendril import version_check
            from tendril.tui.screens.update_modal import UpdateNoticeModal
            self.push_screen(UpdateNoticeModal(version_check.notice(self.update_available)))
        # Fire an incremental sync in the background only if we have projects to refresh.
        # Skipping the JIRA client build when there's nothing to do keeps the empty-cache
        # first-run experience clean (and lets tests skip credentials).
        if self._has_synced_projects():
            self.run_incremental_sync()

    def _has_synced_projects(self) -> bool:
        with self.session_factory() as session:
            return session.query(ProjectSyncState).count() > 0

    def _get_jira(self):
        if self._jira is None:
            self._jira = jira_client.build(self.cfg)
        return self._jira

    def run_incremental_sync(self) -> Worker:
        """Kick off `tendril sync` (incremental refresh) in a background thread. Notifies on completion."""
        return self.run_worker(
            self._worker_incremental_sync,
            group="sync",
            exclusive=True,
            thread=True,
            name="incremental-sync",
        )

    def run_write(
        self,
        label: str,
        fn: Callable[[Any, Any], None],
        on_done: Callable[[], None] | None = None,
    ) -> Worker:
        """Run a JIRA write in a background thread.

        `fn(session, client)` performs the write. On success we show a toast and,
        if provided, call `on_done` on the UI thread (typically to reload a screen).
        """
        def worker() -> None:
            try:
                client = self._get_jira()
                with self.session_factory() as session:
                    fn(session, client)
            except Exception as e:  # noqa: BLE001
                self.record_error(e)
                self.call_from_thread(self.notify, f"{label} failed: {e}", severity="error")
                return
            self.call_from_thread(self.notify, f"{label} ok.")
            if on_done is not None:
                self.call_from_thread(on_done)

        return self.run_worker(worker, group="write", thread=True, name=label)

    def run_project_sync(self, project_key: str, on_done: Callable[[], None] | None = None) -> Worker:
        """Full sync of a JIRA project in the background."""
        return self.run_worker(
            lambda: self._worker_project_sync(project_key, on_done),
            group="sync",
            exclusive=False,
            thread=True,
            name=f"project-sync-{project_key}",
        )

    def _worker_project_sync(self, project_key: str, on_done: Callable[[], None] | None) -> None:
        client = self._get_jira()
        try:
            with self.session_factory() as session:
                rows = sync_project(client, session, project_key, cfg=self.cfg)
        except Exception as e:  # noqa: BLE001
            self.record_error(e)
            self.call_from_thread(
                self.notify, f"Sync {project_key} failed: {e}", severity="error"
            )
            return
        self.call_from_thread(
            self.notify, f"Synced {plural(len(rows), 'issue')} from {project_key}."
        )
        self.call_from_thread(self._reload_top_screen)
        if on_done is not None:
            self.call_from_thread(on_done)

    def run_issue_refresh(self, key: str, on_done: Callable[[], None] | None = None) -> Worker:
        """Refetch a single issue in the background. `on_done` is called on the UI thread."""
        return self.run_worker(
            lambda: self._worker_refresh_issue(key, on_done),
            group="sync",
            exclusive=False,
            thread=True,
            name=f"refresh-{key}",
        )

    # ---- worker bodies (run in threads) ----

    def _worker_incremental_sync(self) -> None:
        client = self._get_jira()
        try:
            with self.session_factory() as session:
                rows = incremental_sync(client, session, cfg=self.cfg)
        except Exception as e:  # noqa: BLE001
            self.record_error(e)
            self.call_from_thread(self.notify, f"Sync failed: {e}", severity="error")
            return
        self.call_from_thread(self.notify, f"Synced {plural(len(rows), 'changed issue')}.")
        self.call_from_thread(self._reload_top_screen)

    def _worker_refresh_issue(self, key: str, on_done: Callable[[], None] | None) -> None:
        client = self._get_jira()
        try:
            with self.session_factory() as session:
                sync_issue(client, session, key, cfg=self.cfg)
        except Exception as e:  # noqa: BLE001
            self.record_error(e)
            self.call_from_thread(self.notify, f"Refresh failed: {e}", severity="error")
            return
        self.call_from_thread(self.notify, f"Refreshed {key}.")
        if on_done is not None:
            self.call_from_thread(on_done)

    # ---- feedback (command palette only; see tendril.feedback) ----

    async def run_action(
        self,
        action: str | ActionParseResult,
        default_namespace: DOMNode | None = None,
        namespaces: Mapping[str, DOMNode] | None = None,
    ) -> bool:
        # Record before dispatch so the action precedes any screen it opens.
        self._record_action(action, default_namespace)
        return await super().run_action(action, default_namespace, namespaces)

    def _record_action(
        self, action: str | ActionParseResult, default_namespace: DOMNode | None
    ) -> None:
        """Remember tendril's own screen/app actions by name. Never the params.

        Widget actions (scrolling, cursor moves) and Textual's built-in actions
        say nothing about what the user was doing, so they are skipped.
        """
        destination, name, _params = parse_action(action) if isinstance(action, str) else action
        if destination == "app":
            target: object = self
        elif destination == "screen":
            target = self.screen
        elif destination:
            return  # other namespaces are widget-level
        else:
            target = default_namespace if default_namespace is not None else self
        if not self._is_tracked(target):
            return
        method = getattr(type(target), f"action_{name}", None) or getattr(
            type(target), f"_action_{name}", None
        )
        if not _defined_in_tendril(method):
            return
        self._recent_actions.append(f"{type(target).__name__}.{name}")

    @staticmethod
    def _is_tracked(target: object) -> bool:
        """Tendril's own screens and app; never the feedback modal itself."""
        return (
            isinstance(target, (Screen, App))
            and _defined_in_tendril(type(target))
            and not isinstance(target, FeedbackModal)
        )

    def push_screen(self, screen: Any, *args: Any, **kwargs: Any) -> Any:
        if self._is_tracked(screen):
            self._recent_actions.append(f"open {type(screen).__name__}")
        return super().push_screen(screen, *args, **kwargs)

    def pop_screen(self) -> Any:
        closing = self.screen_stack[-1] if self.screen_stack else None
        if self._is_tracked(closing):
            self._recent_actions.append(f"close {type(closing).__name__}")
        return super().pop_screen()

    def record_error(self, error: BaseException) -> None:
        """Keep the latest worker failure for a feedback report (sanitized on use)."""
        self._last_error = error

    def feedback_context(self, screen: Screen) -> feedback.FeedbackContext:
        """Allowlisted context for `screen`, the screen the palette was summoned from."""
        stack = list(self.screen_stack)
        if screen in stack:
            stack = stack[: stack.index(screen) + 1]
        # Drop the palette and Textual's default base screen; neither says where the user was.
        stack = [s for s in stack if not isinstance(s, CommandPalette) and type(s) is not Screen]
        focused = screen.focused
        tendril_version, python_version, os_name = feedback.environment()
        return feedback.FeedbackContext(
            tendril_version=tendril_version,
            python_version=python_version,
            os_name=os_name,
            terminal_size=f"{self.size.width}x{self.size.height}",
            screen_stack=tuple(type(s).__name__ for s in stack),
            focused_widget=type(focused).__name__ if focused is not None else None,
            recent_actions=tuple(self._recent_actions),
            error=(
                feedback.sanitize_traceback(self._last_error)
                if self._last_error is not None
                else None
            ),
            config_shape=feedback.config_shape(self.cfg),
        )

    def open_feedback(self, screen: Screen) -> None:
        """Show the feedback preview; on confirm, open the prefilled GitHub issue.

        Deliberately not an `action_*` method: the command palette is the only
        way in, so no key binding or markup link can reach it.
        """
        ctx = self.feedback_context(screen)

        def after(kind: feedback.Kind | None) -> None:
            if kind is None:
                return
            self.open_url(feedback.issue_url(ctx, kind))
            self.notify("Opened GitHub in your browser. Review the issue before you submit it.")

        self.push_screen(FeedbackModal(ctx), after)

    def _reload_top_screen(self) -> None:
        screen = self.screen
        reload = getattr(screen, "reload", None)
        if callable(reload):
            reload()

    def watch_theme(self, theme: str) -> None:
        """Persist theme changes to config so they survive across sessions."""
        if theme == self.cfg.ui.theme:
            return
        self.cfg.ui.theme = theme
        try:
            config_mod.save(self.cfg)
        except OSError as e:
            self.notify(f"Could not save theme: {e}", severity="warning")

    def action_open_search(self) -> None:
        """Global jump-to-issue. Push the picked issue on top of whatever screen is active."""
        from tendril.tui.screens.issue_detail import IssueDetailScreen
        from tendril.tui.screens.search_modal import SearchModal

        def after(key: str | None) -> None:
            if key:
                self.push_screen(IssueDetailScreen(key))

        self.push_screen(SearchModal(), after)

    def action_open_sprint_watchlist(self) -> None:
        from tendril.tui.screens.sprint_watchlist import SprintWatchlistScreen
        self.push_screen(SprintWatchlistScreen())

    def action_open_rollover_picker(self) -> None:
        """Pick a source sprint, then open the two-panel rollover screen for it."""
        from tendril.tui.screens.rollover_picker import RolloverPickerModal
        from tendril.tui.screens.sprint_rollover import SprintRolloverScreen

        def after(sprint_id: int | None) -> None:
            if sprint_id is not None:
                self.push_screen(SprintRolloverScreen(sprint_id))

        self.push_screen(RolloverPickerModal(), after)
