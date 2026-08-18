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
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    """

    def __init__(self, prefill: str | None = None) -> None:
        super().__init__()
        self._prefill = prefill or ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add JIRA key to watchlist (e.g. PROJ-123):")
            yield Input(value=self._prefill, placeholder="PROJ-123", id="key-input")
            yield Label("[dim]enter to confirm · esc to cancel[/dim]")

    def on_mount(self) -> None:
        inp = self.query_one(Input)
        inp.focus()
        if self._prefill:
            inp.cursor_position = len(self._prefill)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
