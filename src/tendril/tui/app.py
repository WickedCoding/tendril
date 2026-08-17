from __future__ import annotations

from typing import Any, Callable

from textual.app import App
from textual.worker import Worker

from tendril.config import Config
from tendril.db.engine import build_engine, session_factory as make_session_factory
from tendril.db.schema import init_schema
from tendril.db.models import ProjectSyncState
from tendril.jira import client as jira_client
from tendril.sync.commands import incremental_sync, sync_issue, sync_project
from tendril.text import plural
from tendril.tui.commands import SyncCommands
from tendril.tui.screens.watchlist import WatchlistScreen


class TendrilApp(App):
    """Textual app root. Holds the SQLAlchemy session factory and JIRA client."""

    TITLE = "tendril"
    COMMANDS = App.COMMANDS | {SyncCommands}

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        engine = build_engine()
        init_schema(engine)
        self.session_factory = make_session_factory(engine)
        self._jira = None  # lazy — do not hit keyring until needed

    def on_mount(self) -> None:
        self.push_screen(WatchlistScreen())
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
        """Kick off `sync incremental` in a background thread. Notifies on completion."""
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
                rows = sync_project(client, session, project_key)
        except Exception as e:  # noqa: BLE001
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
                rows = incremental_sync(client, session)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Sync failed: {e}", severity="error")
            return
        self.call_from_thread(self.notify, f"Synced {plural(len(rows), 'changed issue')}.")
        self.call_from_thread(self._reload_top_screen)

    def _worker_refresh_issue(self, key: str, on_done: Callable[[], None] | None) -> None:
        client = self._get_jira()
        try:
            with self.session_factory() as session:
                sync_issue(client, session, key)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Refresh failed: {e}", severity="error")
            return
        self.call_from_thread(self.notify, f"Refreshed {key}.")
        if on_done is not None:
            self.call_from_thread(on_done)

    def _reload_top_screen(self) -> None:
        screen = self.screen
        reload = getattr(screen, "reload", None)
        if callable(reload):
            reload()
