from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Select, Static

from tendril.db.models import LinkType
from tendril.tui.screens.link_modal import _default_value, _directional_options


_DESCRIPTION_MAX_LINES = 12


def _shorten_description(text: Text | None, max_lines: int = _DESCRIPTION_MAX_LINES) -> Text | None:
    """Cap a rendered description at `max_lines`, appending an ellipsis line when truncated.

    Blank leading/trailing lines are trimmed so the preview doesn't waste rows.
    Returns None if the input is empty or entirely whitespace.
    """
    if text is None:
        return None
    lines = text.split("\n")
    while lines and not lines[0].plain.strip():
        lines = lines[1:]
    while lines and not lines[-1].plain.strip():
        lines = lines[:-1]
    if not lines:
        return None
    truncated = len(lines) > max_lines
    kept = lines[:max_lines]
    joined = Text("\n").join(kept)
    if truncated:
        joined.append("\n…", style="dim")
    return joined


class SurfaceCardModal(ModalScreen[tuple[str, str] | None]):
    """Detail view of a surfaced alert issue with a link-type chooser.

    Dismisses with `(type_name, direction)` on submit, or None on cancel.
    The caller already knows the source (viewed issue) and target (alert-owning issue),
    so this modal only collects the link type + direction.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    DEFAULT_CSS = """
    SurfaceCardModal { align: center middle; }
    SurfaceCardModal > Vertical {
        width: 70; height: auto; padding: 1 2;
        background: $surface; border: round $primary;
    }
    SurfaceCardModal .summary { margin-bottom: 1; }
    SurfaceCardModal #description-preview { margin-top: 1; margin-bottom: 1; color: $text-muted; }
    SurfaceCardModal Select { margin-bottom: 1; }
    """

    def __init__(
        self,
        *,
        target_key: str,
        status: str | None,
        summary: str | None,
        shared_tags: list[str],
        link_types: list[LinkType],
        default_link_type: str,
        description: Text | None = None,
    ) -> None:
        super().__init__()
        self.target_key = target_key
        self.status = status or "—"
        self.summary = summary or ""
        self.shared_tags = shared_tags
        self._link_types = link_types
        self.default_link_type = default_link_type
        self._description = _shorten_description(description)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.target_key}[/bold] · {self.status}")
            yield Label(self.summary, classes="summary")
            if self.shared_tags:
                yield Label(f"[dim]shared: {' · '.join('#' + t for t in self.shared_tags)}[/dim]")
            if self._description is not None:
                yield Static(self._description, id="description-preview", markup=False)
            yield Label("Relationship:")
            if self._link_types:
                yield Select(
                    _directional_options(self._link_types),
                    id="link-type",
                    value=_default_value(self._link_types, self.default_link_type),
                    allow_blank=False,
                )
            else:
                yield Label(
                    "[yellow]No link types cached. Run `tendril sync link-types` first.[/yellow]",
                    id="link-type-empty",
                )
            yield Label("[dim]ctrl+s creates the link · esc cancels[/dim]")

    def on_mount(self) -> None:
        if self._link_types:
            self.query_one("#link-type", Select).focus()

    def action_submit(self) -> None:
        if not self._link_types:
            self.dismiss(None)
            return
        value = self.query_one("#link-type", Select).value
        if value is Select.BLANK:
            self.dismiss(None)
            return
        name, direction = value  # type: ignore[misc]
        self.dismiss((name, direction))

    def action_cancel(self) -> None:
        self.dismiss(None)
