from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class SurfaceCardModal(ModalScreen[str | None]):
    """Detail view of a surfaced alert issue with a link-type prompt.

    Dismisses with the chosen link type on submit, or None on cancel.
    The caller already knows the source (viewed issue) and target (alert-owning issue),
    so this modal only collects the link type.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    SurfaceCardModal { align: center middle; }
    SurfaceCardModal > Vertical {
        width: 70; padding: 1 2;
        background: $surface; border: round $primary;
    }
    SurfaceCardModal .summary { margin-bottom: 1; }
    """

    def __init__(
        self,
        *,
        target_key: str,
        status: str | None,
        summary: str | None,
        shared_tags: list[str],
        default_link_type: str,
    ) -> None:
        super().__init__()
        self.target_key = target_key
        self.status = status or "—"
        self.summary = summary or ""
        self.shared_tags = shared_tags
        self.default_link_type = default_link_type

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.target_key}[/bold] · {self.status}")
            yield Label(self.summary, classes="summary")
            if self.shared_tags:
                yield Label(f"[dim]shared: {' · '.join('#' + t for t in self.shared_tags)}[/dim]")
            yield Label(f"Link type  [dim](default: {self.default_link_type})[/dim]:")
            yield Input(id="link-type", placeholder=self.default_link_type)
            yield Label("[dim]enter creates the link · esc cancels[/dim]")

    def on_mount(self) -> None:
        self.query_one("#link-type", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        link_type = event.value.strip() or self.default_link_type
        self.dismiss(link_type)

    def action_cancel(self) -> None:
        self.dismiss(None)
