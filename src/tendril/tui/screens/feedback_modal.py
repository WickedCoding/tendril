from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from tendril.feedback import PUBLIC_WARNING, FeedbackContext, Kind, render_context


class FeedbackModal(ModalScreen["Kind | None"]):
    """Preview of the content-free feedback report. Dismisses with "bug", "idea" or None."""

    BINDINGS = [
        Binding("b", "choose('bug')", "Bug"),
        Binding("i", "choose('idea')", "Idea"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    FeedbackModal { align: center middle; }
    FeedbackModal > Vertical {
        width: 90; height: auto; max-height: 90%; padding: 1 2;
        background: $surface; border: round $primary;
    }
    FeedbackModal .title { text-style: bold; margin-bottom: 1; }
    FeedbackModal .warning { color: $warning; margin-bottom: 1; }
    FeedbackModal VerticalScroll { height: auto; max-height: 20; border: round $panel; }
    FeedbackModal .hint { margin-top: 1; color: $text-muted; }
    """

    def __init__(self, ctx: FeedbackContext) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Send feedback", classes="title")
            yield Static(PUBLIC_WARNING, classes="warning", markup=False)
            yield Label("Tendril adds only this context. You write the rest on GitHub.")
            with VerticalScroll():
                yield Static(render_context(self._ctx), id="feedback-context", markup=False)
            yield Label(
                "b bug report · i idea · esc cancel. Opens GitHub in your browser.",
                classes="hint",
            )

    def action_choose(self, kind: str) -> None:
        if kind in ("bug", "idea"):
            self.dismiss(kind)  # type: ignore[arg-type]

    def action_cancel(self) -> None:
        self.dismiss(None)
