from __future__ import annotations

from functools import partial

from sqlalchemy import select
from textual.command import DiscoveryHit, Hit, Hits, Provider

from tendril.db.models import ProjectSyncState
from tendril.tui.screens.project_modal import ProjectKeyModal


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
