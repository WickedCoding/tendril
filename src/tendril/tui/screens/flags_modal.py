from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class FlagsModal(ModalScreen[list[str] | None]):
    """Edit the feature-flags multi-select.

    Dismisses with a list of values (empty list clears all flags) or None on cancel.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    FlagsModal { align: center middle; }
    FlagsModal > Vertical {
        width: 70; padding: 1 2;
        background: $surface; border: round $primary;
    }
    """

    def __init__(self, current: list[str]) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Feature flags  [dim]comma-separated · empty clears all[/dim]")
            yield Input(value=", ".join(self.current), placeholder="flag_a, flag_b", id="flags")
            yield Label("[dim]enter saves · esc cancels[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        values = [v.strip() for v in raw.split(",") if v.strip()] if raw else []
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)
