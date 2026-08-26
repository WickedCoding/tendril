from __future__ import annotations

from functools import partial

from sqlalchemy import select
from textual.command import DiscoveryHit, Hit, Hits, Provider

from tendril.db.models import ProjectSyncState
from tendril.tui.screens.project_modal import ProjectKeyModal
from tendril.tui.sorting import SortableTable


class SyncCommands(Provider):
    """Command-palette entries for kicking off syncs.

    Exposes one always-available "Sync project…" (prompts for a key) and one
    "Sync project KEY" shortcut per project previously synced.
    """

    def _project_keys(self) -> list[str]:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            return list(session.scalars(
                select(ProjectSyncState.project_key).order_by(ProjectSyncState.project_key)
            ).all())

    def _open_prompt(self) -> None:
        def after(key: str | None) -> None:
            if key:
                self.app.run_project_sync(key)  # type: ignore[attr-defined]
        self.app.push_screen(ProjectKeyModal(), after)

    def _sync(self, project_key: str) -> None:
        self.app.run_project_sync(project_key)  # type: ignore[attr-defined]

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            "Sync project…",
            self._open_prompt,
            help="Prompt for a JIRA project key and pull every issue into the cache.",
        )
        for key in self._project_keys():
            yield DiscoveryHit(
                f"Sync project {key}",
                partial(self._sync, key),
                help=f"Refresh all issues in project {key}.",
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        prompt_label = "Sync project…"
        prompt_score = matcher.match(prompt_label)
        if prompt_score > 0:
            yield Hit(
                prompt_score,
                matcher.highlight(prompt_label),
                self._open_prompt,
                help="Prompt for a JIRA project key and pull every issue into the cache.",
            )
        for key in self._project_keys():
            label = f"Sync project {key}"
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    partial(self._sync, key),
                    help=f"Refresh all issues in project {key}.",
                )


class SortCommands(Provider):
    """Sort entries for whichever sortable table the current screen exposes.

    The active screen — the top of the app's screen stack — is asked for its
    columns via the SortableTable protocol; if it doesn't implement one, the
    provider yields nothing and the palette shows no sort options.
    """

    def _sortable(self) -> SortableTable | None:
        # `self.screen` is the screen the palette was summoned from — using
        # `self.app.screen` here would return the palette itself.
        screen = self.screen
        return screen if isinstance(screen, SortableTable) else None

    def _apply(self, screen: SortableTable, key: str, descending: bool) -> None:
        screen.apply_sort(key, descending)

    def _entries(self, screen: SortableTable) -> list[tuple[str, str, bool]]:
        """`(label, column_key, descending)` for every column × direction."""
        out: list[tuple[str, str, bool]] = []
        for col in screen.sort_options():
            out.append((f"Sort by {col.label} ↑", col.key, False))
            out.append((f"Sort by {col.label} ↓", col.key, True))
        return out

    async def discover(self) -> Hits:
        screen = self._sortable()
        if screen is None:
            return
        for label, key, desc in self._entries(screen):
            yield DiscoveryHit(
                label,
                partial(self._apply, screen, key, desc),
                help=f"Sort the current table by {key} "
                f"{'descending' if desc else 'ascending'}.",
            )

    async def search(self, query: str) -> Hits:
        screen = self._sortable()
        if screen is None:
            return
        matcher = self.matcher(query)
        for label, key, desc in self._entries(screen):
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    partial(self._apply, screen, key, desc),
                    help=f"Sort the current table by {key} "
                    f"{'descending' if desc else 'ascending'}.",
                )
