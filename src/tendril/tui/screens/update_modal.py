from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class UpdateNoticeModal(ModalScreen[None]):
    """Launch-time popup announcing a newer tendril release on PyPI."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    DEFAULT_CSS = """
    UpdateNoticeModal { align: center middle; }
    UpdateNoticeModal > Vertical {
        width: 70; height: auto; padding: 1 2;
        background: $surface; border: round $warning;
    }
    UpdateNoticeModal .title { text-style: bold; color: $warning; margin-bottom: 1; }
    UpdateNoticeModal .hint { margin-top: 1; color: $text-muted; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Update available", classes="title")
            yield Static(self._message, id="update-message", markup=False)
            yield Label("Press Enter or Esc to continue.", classes="hint")

    def action_close(self) -> None:
        self.dismiss(None)
