from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class AddToWatchlistModal(ModalScreen[str | None]):
    """Prompt for a JIRA issue key. Dismisses with the key (str) or None on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddToWatchlistModal {
        align: center middle;
    }
    AddToWatchlistModal > Vertical {
        width: 60;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add JIRA key to watchlist (e.g. PROJ-123):")
            yield Input(placeholder="PROJ-123", id="key-input")
            yield Label("[dim]enter to confirm · esc to cancel[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
