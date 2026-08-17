from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class LinkModal(ModalScreen[tuple[str, str] | None]):
    """Ask for target key + link type. Dismisses with (target_key, link_type) or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    LinkModal { align: center middle; }
    LinkModal > Vertical {
        width: 60; padding: 1 2;
        background: $surface; border: round $primary;
    }
    """

    def __init__(self, default_link_type: str = "Relates") -> None:
        super().__init__()
        self.default_link_type = default_link_type

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Link this issue to (JIRA key):")
            yield Input(id="target", placeholder="PROJ-123")
            yield Label(f"Link type  [dim](default: {self.default_link_type})[/dim]:")
            yield Input(id="link-type", placeholder=self.default_link_type)
            yield Label("[dim]enter on either field advances/submits · esc cancels[/dim]")

    def on_mount(self) -> None:
        self.query_one("#target", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "target":
            self.query_one("#link-type", Input).focus()
            return
        self._submit()

    def _submit(self) -> None:
        target = self.query_one("#target", Input).value.strip()
        if not target:
            self.dismiss(None)
            return
        link_type = self.query_one("#link-type", Input).value.strip() or self.default_link_type
        self.dismiss((target, link_type))

    def action_cancel(self) -> None:
        self.dismiss(None)
