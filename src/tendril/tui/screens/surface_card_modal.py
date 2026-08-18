from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Select

from tendril.db.models import LinkType
from tendril.tui.screens.link_modal import _default_value, _directional_options


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
        width: 70; padding: 1 2;
        background: $surface; border: round $primary;
    }
    SurfaceCardModal .summary { margin-bottom: 1; }
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
    ) -> None:
        super().__init__()
        self.target_key = target_key
        self.status = status or "—"
        self.summary = summary or ""
        self.shared_tags = shared_tags
        self._link_types = link_types
        self.default_link_type = default_link_type

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.target_key}[/bold] · {self.status}")
            yield Label(self.summary, classes="summary")
            if self.shared_tags:
                yield Label(f"[dim]shared: {' · '.join('#' + t for t in self.shared_tags)}[/dim]")
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
