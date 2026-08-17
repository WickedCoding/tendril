from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea


class CommentModal(ModalScreen[str | None]):
    """Multi-line comment input. Dismisses with the body (str) or None on cancel/empty."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    DEFAULT_CSS = """
    CommentModal { align: center middle; }
    CommentModal > Vertical {
        width: 80; height: 22; padding: 1 2;
        background: $surface; border: round $primary;
    }
    CommentModal TextArea { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add a comment  [dim]· ctrl+s submit · esc cancel[/dim]")
            yield TextArea(id="body")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def action_submit(self) -> None:
        body = self.query_one(TextArea).text.strip()
        self.dismiss(body or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
