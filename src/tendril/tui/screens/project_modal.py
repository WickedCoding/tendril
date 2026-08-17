from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class ProjectKeyModal(ModalScreen[str | None]):
    """Prompt for a JIRA project key. Dismisses with the key (str) or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ProjectKeyModal { align: center middle; }
    ProjectKeyModal > Vertical {
        width: 60; padding: 1 2;
        background: $surface; border: round $primary;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Sync JIRA project (key, e.g. MMINT):")
            yield Input(placeholder="MMINT", id="project-input")
            yield Label("[dim]enter to sync · esc to cancel[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip().upper()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
