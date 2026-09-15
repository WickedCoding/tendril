from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class ReductionModal(ModalScreen[float | None]):
    """Capture the SP reduction for a single carry-over issue.

    Dismisses with the new reduction (0.0 clears any previous value) or None
    on cancel. The value is local-only — never written to JIRA — and feeds
    `carryover_totals` to shape the projected right-panel totals.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ReductionModal { align: center middle; }
    ReductionModal > Vertical {
        width: 60; padding: 1 2;
        background: $surface; border: round $primary;
    }
    ReductionModal #reduction-hint { color: $text-muted; }
    """

    def __init__(
        self,
        issue_key: str,
        current_reduction: float,
        original_sp: float | None,
    ) -> None:
        super().__init__()
        self._key = issue_key
        self._current = current_reduction
        self._original = original_sp

    def compose(self) -> ComposeResult:
        sp = _fmt(self._original) if self._original is not None else "—"
        remaining = _fmt(max(0.0, (self._original or 0.0) - self._current))
        with Vertical():
            yield Label(f"Reduce SP for [bold]{self._key}[/bold]")
            yield Label(
                f"[dim]original: {sp} SP · current remaining: {remaining} SP[/dim]",
                id="reduction-hint",
            )
            yield Input(
                value=_fmt(self._current) if self._current else "",
                placeholder="0",
                id="reduction-input",
            )
            yield Label("[dim]enter saves · esc cancels · empty clears[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            self.dismiss(0.0)
            return
        try:
            self.dismiss(float(raw))
        except ValueError:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"
