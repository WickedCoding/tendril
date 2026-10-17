from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option


class ProjectFilterModal(ModalScreen[str | None]):
    """Choose a cached project: empty string clears the filter, None cancels."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_results", "Results", show=False),
    ]

    DEFAULT_CSS = """
    ProjectFilterModal { align: center middle; }
    ProjectFilterModal > Vertical {
        width: 60; max-width: 90%; height: 20; max-height: 90%;
        padding: 1 2; background: $surface; border: round $primary;
    }
    ProjectFilterModal OptionList { height: 1fr; }
    """

    def __init__(self, projects: list[str], current: str | None) -> None:
        super().__init__()
        self.projects = projects
        self.current = current or ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Filter by project")
            yield Input(placeholder="Search cached projects…", id="project-search")
            yield OptionList(id="project-options")
            yield Label("[dim]enter to select · ↓ to browse · esc to cancel[/dim]")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def _populate(self, query: str) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        query = query.strip().casefold()
        highlighted = 0
        for key in ["", *self.projects]:
            label = key or "All projects"
            if query not in label.casefold():
                continue
            prompt = Text(("✓ " if key == self.current else "  ") + label)
            options.add_option(Option(prompt, id="project:" + key))
            if key == self.current:
                highlighted = options.option_count - 1
        options.highlighted = highlighted if options.option_count else None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        options = self.query_one(OptionList)
        if options.highlighted is not None:
            self._select(options.get_option_at_index(options.highlighted))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._select(event.option)

    def _select(self, option: Option) -> None:
        if option.id is not None:
            self.dismiss(option.id.removeprefix("project:"))

    def action_focus_results(self) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            options.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
