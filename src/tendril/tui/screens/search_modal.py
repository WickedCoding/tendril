from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from tendril.db.models import Issue
from tendril.sync.commands import search_issues


class SearchModal(ModalScreen[str | None]):
    """Global fuzzy-lite jump-to-issue. Dismisses with the selected key or None."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_results", "Results", show=False),
    ]

    DEFAULT_CSS = """
    SearchModal { align: center middle; }
    SearchModal > Vertical {
        width: 80%;
        max-width: 100;
        height: 24;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    SearchModal #search-input { margin-bottom: 1; }
    SearchModal #results { height: 1fr; }
    SearchModal #search-hint { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(
                placeholder="search key, tag, or summary — prefix #tag for tag-only…",
                id="search-input",
            )
            yield OptionList(id="results")
            yield Label(
                "[dim]enter to open · ↓ to browse results · esc to cancel[/dim]",
                id="search-hint",
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._repopulate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        results = self.query_one(OptionList)
        if results.option_count == 0:
            return
        highlighted = results.highlighted or 0
        option = results.get_option_at_index(highlighted)
        if option.id:
            self.dismiss(option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_focus_results(self) -> None:
        results = self.query_one(OptionList)
        if results.option_count > 0:
            results.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _repopulate(self, query: str) -> None:
        results = self.query_one(OptionList)
        results.clear_options()
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            matches = search_issues(session, query)
        for issue in matches:
            results.add_option(Option(_format_row(issue), id=issue.key))


def _format_row(issue: Issue) -> Text:
    row = Text()
    row.append(issue.key, style="bold")
    row.append("  ·  ")
    row.append(issue.status or "—")
    row.append("  ·  ")
    summary = (issue.summary or "").strip() or "—"
    row.append(summary, style="dim")
    row.truncate(200, overflow="ellipsis")
    return row
