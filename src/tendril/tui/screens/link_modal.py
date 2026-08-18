from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Select

from tendril.db.models import LinkType


class LinkModal(ModalScreen[tuple[str, str, str] | None]):
    """Ask for target key + directional link type.

    Dismisses with `(target_key, type_name, direction)` or None. `direction` reads
    from the source's perspective — 'outward' means source uses the outward phrase
    (e.g. `source blocks target` for type "Blocks").
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    DEFAULT_CSS = """
    LinkModal { align: center middle; }
    LinkModal > Vertical {
        width: 60; padding: 1 2;
        background: $surface; border: round $primary;
    }
    LinkModal Select { margin-bottom: 1; }
    """

    def __init__(
        self,
        link_types: list[LinkType],
        default_link_type: str = "Relates",
    ) -> None:
        super().__init__()
        self._link_types = link_types
        self.default_link_type = default_link_type

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Link this issue to (JIRA key):")
            yield Input(id="target", placeholder="PROJ-123")
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
            yield Label("[dim]enter on key advances · ctrl+s submits · esc cancels[/dim]")

    def on_mount(self) -> None:
        self.query_one("#target", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "target" and self._link_types:
            self.query_one("#link-type", Select).focus()

    def action_submit(self) -> None:
        target = self.query_one("#target", Input).value.strip()
        if not target or not self._link_types:
            self.dismiss(None)
            return
        value = self.query_one("#link-type", Select).value
        if value is Select.BLANK:
            self.dismiss(None)
            return
        name, direction = value  # type: ignore[misc]
        self.dismiss((target, name, direction))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _directional_options(link_types: list[LinkType]) -> list[tuple[str, tuple[str, str]]]:
    """Flatten each link type into its two directional options for a Select widget."""
    out: list[tuple[str, tuple[str, str]]] = []
    for lt in link_types:
        out.append((lt.outward, (lt.name, "outward")))
        # Skip the inward variant when both phrases are identical (e.g. "Relates" / "relates to").
        if lt.inward != lt.outward:
            out.append((lt.inward, (lt.name, "inward")))
    return out


def _default_value(link_types: list[LinkType], default_name: str) -> tuple[str, str]:
    """Pick the (name, 'outward') pair for `default_name` if present, else the first option."""
    for lt in link_types:
        if lt.name == default_name:
            return (lt.name, "outward")
    first = link_types[0]
    return (first.name, "outward")
