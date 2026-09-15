from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from tendril.sync.rollover import list_active_sprints


class RolloverPickerModal(ModalScreen[int | None]):
    """Pick the source sprint for a rollover. Dismisses with a sprint id or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    RolloverPickerModal { align: center middle; }
    RolloverPickerModal > Vertical {
        width: 80%;
        max-width: 100;
        height: 20;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    RolloverPickerModal #picker-title { margin-bottom: 1; }
    RolloverPickerModal #picker-list { height: 1fr; }
    RolloverPickerModal #picker-hint { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Choose the source sprint to roll over:", id="picker-title")
            yield OptionList(id="picker-list")
            yield Label(
                "[dim]enter to open · esc to cancel[/dim]",
                id="picker-hint",
            )

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            sprints = list_active_sprints(session)
        if not sprints:
            options.add_option(Option(
                Text("No active sprints in the cache. Run `tendril sync project KEY` first.", style="dim"),
                id=None,
                disabled=True,
            ))
            return
        for sprint in sprints:
            options.add_option(Option(_format_row(sprint), id=str(sprint.id)))
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        try:
            self.dismiss(int(event.option.id))
        except ValueError:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _format_row(sprint) -> Text:  # type: ignore[no-untyped-def]
    row = Text()
    row.append(sprint.name, style="bold")
    if sprint.goal:
        row.append("  ·  ")
        row.append((sprint.goal or "").strip(), style="dim")
    row.truncate(200, overflow="ellipsis")
    return row
