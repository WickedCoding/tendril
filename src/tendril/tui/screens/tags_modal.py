from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class TagsModal(ModalScreen[list[str] | None]):
    """Edit the local tag set on an issue.

    Dismisses with the new tag list (empty list clears all tags) or None on cancel.
    Tags are local — never pushed to JIRA.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    TagsModal { align: center middle; }
    TagsModal > Vertical {
        width: 70; padding: 1 2;
        background: $surface; border: round $primary;
    }
    """

    def __init__(self, current: list[str]) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tags  [dim]comma-separated · empty clears all[/dim]")
            yield Input(value=", ".join(self.current), placeholder="logo, branding", id="tags")
            yield Label("[dim]enter saves · esc cancels[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        values = [v.strip() for v in raw.split(",") if v.strip()] if raw else []
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)
