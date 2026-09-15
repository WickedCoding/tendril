from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from tendril.db.models import Issue
from tendril.sync.rollover import SprintTotals


class RolloverPreviewModal(ModalScreen[bool]):
    """Final confirmation before executing the rollover.

    Dismisses True if the user confirms (`enter`), False otherwise (`escape` / `q`).
    The screen only presents data — the actual JIRA writes are the caller's job.
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("y", "confirm", "Confirm"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    RolloverPreviewModal { align: center middle; }
    RolloverPreviewModal > Vertical {
        width: 90%;
        max-width: 200;
        height: 90%;
        max-height: 60;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    RolloverPreviewModal #preview-title { padding-bottom: 1; }
    RolloverPreviewModal #preview-summary { padding-bottom: 1; }
    RolloverPreviewModal #preview-list { height: 1fr; padding: 0 1; }
    RolloverPreviewModal #preview-hint { color: $text-muted; padding-top: 1; }
    """

    def __init__(
        self,
        *,
        source_name: str,
        target_name: str,
        carried_issues: list[Issue],
        existing_target_issues: list[Issue],
        projected_totals: SprintTotals,
        tracked_skills: list[str],
    ) -> None:
        super().__init__()
        self._source_name = source_name
        self._target_name = target_name
        self._carried = carried_issues
        self._existing = existing_target_issues
        self._totals = projected_totals
        self._tracked = list(tracked_skills)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                Text.assemble(
                    ("Rollover: ", "bold"),
                    (self._source_name, "bold"),
                    (" → ", "dim"),
                    (self._target_name, "bold"),
                ),
                id="preview-title",
            )
            yield Static(self._summary_text(), id="preview-summary")
            yield VerticalScroll(
                Static(self._issue_list_text(), id="preview-list-inner"),
                id="preview-list",
            )
            yield Label(
                "[dim]enter / y to confirm · esc / q to cancel[/dim]",
                id="preview-hint",
            )

    def _summary_text(self) -> Text:
        text = Text()
        n_move = len(self._carried)
        n_total = n_move + len(self._existing)
        text.append(
            f"{n_move} issue{'s' if n_move != 1 else ''} will move · "
            f"{n_total} issue{'s' if n_total != 1 else ''} in target after rollover.\n",
            style="bold",
        )
        text.append(
            f"Projected target totals: total {_fmt(self._totals.total)}SP · "
            f"to-do+in-progress {_fmt(self._totals.to_do + self._totals.in_progress)}SP"
        )
        for skill in self._tracked:
            value = self._totals.per_skill.get(skill, 0.0)
            text.append(f" · {skill}: {_fmt(value)}SP")
        return text

    def _issue_list_text(self) -> Text:
        """Full projected roster: carry-overs first (marked `→`), then existing target rows."""
        text = Text()
        first = True

        text.append("Carry-over", style="bold underline")
        text.append(f"  ({len(self._carried)})\n", style="dim")
        if self._carried:
            for issue in self._carried:
                if not first:
                    text.append("\n")
                _append_issue_row(text, issue, marker="→", marker_style="cyan bold")
                first = False
        else:
            text.append("(no issues selected — nothing will move)", style="dim")
            first = False

        text.append("\n\n")
        text.append("Already in target", style="bold underline")
        text.append(f"  ({len(self._existing)})\n", style="dim")
        if self._existing:
            first_existing = True
            for issue in self._existing:
                if not first_existing:
                    text.append("\n")
                _append_issue_row(text, issue, marker=" ", marker_style="dim")
                first_existing = False
        else:
            text.append("(target sprint is empty)", style="dim")
        return text

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _append_issue_row(text: Text, issue: Issue, *, marker: str, marker_style: str) -> None:
    """One issue row: `{marker} KEY [SP] status  summary`, styled for a preview list."""
    sp = _fmt(issue.story_points) if issue.story_points is not None else "—"
    text.append(f"{marker} ", style=marker_style)
    text.append(f"{issue.key}", style="bold")
    text.append(f"  [{sp} SP]  ", style="dim")
    text.append(issue.status or "—", style="dim")
    text.append("  ")
    text.append((issue.summary or "").strip() or "—")


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"
