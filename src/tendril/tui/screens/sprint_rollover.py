from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from tendril.db.models import Issue, RolloverAttempt, Sprint
from tendril.operations import ops as write_ops
from tendril.sync.rollover import (
    SprintTotals,
    TargetResolution,
    carryover_totals,
    compute_totals,
    resolve_target_sprint,
    source_sprint_issues,
)
from tendril.tui.screens.rollover_preview import RolloverPreviewModal
from tendril.tui.screens.rollover_reduction_modal import ReductionModal

# Fixed-width columns shared by both tables: mark(2) + key(15) + status(20) + SP(7)
# plus a small cushion for column separators the DataTable inserts.
# SP is 7 to fit `13→10`-style split labels when a reduction is set.
_FIXED_COLS = 2 + 15 + 20 + 7
_COL_CUSHION = 6


class SprintRolloverScreen(Screen):
    """Two-panel view: source sprint (left) → projected next sprint (right).

    Both panels list issues. A double-line strip above them shows SP totals for
    the source (Active) and the projected next sprint (Future), each with total,
    to-do+in-progress subtotal, and per-tracked-skill totals.

    Preview + execution live in Phase 6.
    """

    BINDINGS = [
        Binding("space", "toggle_selection", "Toggle"),
        Binding("a", "select_all", "Select all"),
        Binding("n", "select_none", "Select none"),
        Binding("e", "edit_reduction", "Edit SP"),
        Binding("c", "open_preview", "Confirm…"),
        Binding("R", "resume", "Resume"),
        Binding("r", "refresh", "Reload"),
        # Priority so the screen intercepts before DataTable's default page nav.
        # On the source panel we forward to the table's own paging; on the
        # target panel we swap the cursor row up/down within `_target_order`.
        Binding("pageup", "move_or_page_up", "Move ↑ / page", priority=True),
        Binding("pagedown", "move_or_page_down", "Move ↓ / page", priority=True),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    SprintRolloverScreen #rollover-totals {
        height: 1;
    }
    SprintRolloverScreen #totals-active {
        width: 1fr; height: 1; padding: 0 1;
    }
    SprintRolloverScreen #totals-future {
        width: 1fr; height: 1; padding: 0 1 0 2;
    }
    SprintRolloverScreen #rollover-body { height: 1fr; }
    SprintRolloverScreen #rollover-left {
        width: 1fr; height: 1fr; padding: 0 1 0 1;
    }
    SprintRolloverScreen #rollover-right {
        width: 1fr; height: 1fr; padding: 0 1 0 2;
        border-left: solid $panel;
    }
    SprintRolloverScreen #source-header,
    SprintRolloverScreen #target-header { height: 1; color: $text-muted; }
    SprintRolloverScreen #source-table,
    SprintRolloverScreen #target-table { height: 1fr; }
    SprintRolloverScreen #rollover-status { color: $text-muted; padding: 0 1; height: 1; }
    """

    def __init__(self, source_sprint_id: int) -> None:
        super().__init__()
        self.source_sprint_id = source_sprint_id
        self._issues: list[Issue] = []
        self._selected: set[str] = set()
        self._reductions: dict[str, float] = {}
        self._source: Sprint | None = None
        self._resolution: TargetResolution | None = None
        self._target_issues: list[Issue] = []
        self._partial_attempt: RolloverAttempt | None = None
        # Ordered display sequence for the target panel: carry-over keys first,
        # then existing target-sprint keys. Seeded from `_sort_issues` on first
        # load and mutated by PgUp/PgDn in the target panel; drives both the
        # panel render and the JIRA rank payload on rollover confirmation.
        self._target_order: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="rollover-totals"):
            yield Static("", id="totals-active")
            yield Static("", id="totals-future")
        with Horizontal(id="rollover-body"):
            with Vertical(id="rollover-left"):
                yield Static("", id="source-header")
                yield DataTable(
                    id="source-table",
                    cursor_type="row",
                    zebra_stripes=True,
                )
            with Vertical(id="rollover-right"):
                yield Static("", id="target-header")
                yield DataTable(
                    id="target-table",
                    cursor_type="row",
                    zebra_stripes=True,
                )
        yield Static("", id="rollover-status")
        yield Footer()

    def on_mount(self) -> None:
        for table_id, mark_header in (("#source-table", "✓"), ("#target-table", " ")):
            table = self.query_one(table_id, DataTable)
            table.add_column(mark_header, width=2, key="mark")
            table.add_column("key", width=15, key="key")
            table.add_column("status", width=20, key="status")
            table.add_column("SP", width=7, key="sp")
            table.add_column("summary", width=40, key="summary")
        # Target panel is interactive but restricted: focus + cursor + PgUp/PgDn
        # reorder only. Space, `e`, and the other source-panel actions bail when
        # the target has focus (see the `_target_has_focus` guards).
        self.query_one("#target-table", DataTable).can_focus = True
        self.reload()
        # Panel widths are unreliable during on_mount; queue a resize once the
        # layout settles so summary columns bind to the panel, not the screen.
        self.call_after_refresh(self._resize_columns)

    def on_resize(self) -> None:
        self._resize_columns()

    def _resize_columns(self) -> None:
        left_panel_w = self.query_one("#rollover-left").size.width
        right_panel_w = self.query_one("#rollover-right").size.width
        left = self.query_one("#source-table", DataTable)
        right = self.query_one("#target-table", DataTable)
        left.columns["summary"].width = max(20, left_panel_w - _FIXED_COLS - _COL_CUSHION)
        right.columns["summary"].width = max(20, right_panel_w - _FIXED_COLS - _COL_CUSHION)

    # ---- data ----

    def reload(self) -> None:
        cfg = self.app.cfg  # type: ignore[attr-defined]
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            self._source = session.get(Sprint, self.source_sprint_id)
            if self._source is None:
                self._set_status(
                    f"Source sprint {self.source_sprint_id} is not in the cache. "
                    "Run `tendril sync incremental` and try again."
                )
                return
            self._issues = source_sprint_issues(session, self.source_sprint_id)
            self._resolution = resolve_target_sprint(session, cfg, self._source)
            if self._resolution.target is not None:
                self._target_issues = source_sprint_issues(
                    session, self._resolution.target.id
                )
            else:
                self._target_issues = []
            self._partial_attempt = session.get(RolloverAttempt, self.source_sprint_id)

        rollover_statuses = set(cfg.rollover.statuses)
        preselect = {
            issue.key for issue in self._issues
            if issue.status in rollover_statuses
        }
        # Only preselect on first load; preserve user toggles across refresh.
        if not self._selected and preselect:
            self._selected = preselect

        # A partial attempt outranks the config preselection: the user has
        # already committed to that key list once, so surface it as the
        # selection so the "resume" plan is exactly what will move.
        if self._partial_attempt is not None:
            self._selected = set(self._partial_attempt.selected_issue_keys)
            # And restore the ordering the user committed to in the previous
            # attempt so a resume ranks JIRA the same way as the first try.
            self._target_order = [
                k for k in self._partial_attempt.target_order_keys
                if k in self._selected or k in {i.key for i in self._target_issues}
            ]

        self._reconcile_target_order()
        self._render_source_panel()
        self._render_target_panel()
        self._render_totals_strip()
        self._set_status(self._status_text())

    def _reconcile_target_order(self) -> None:
        """Bring `_target_order` in line with the current selection + target rows.

        Rules, in order:
        - Drop keys that are neither a carry nor an existing target row.
        - Append newly-selected carry-overs at the top (before any pre-existing
          key that survived), so new picks land where the eye expects them.
        - Append newly-appearing target rows (rare: only after a refresh brings
          a new issue into the target sprint) at the end, `_sort_issues`-ordered.
        - Preserve every key already in `_target_order` in its current slot.
        """
        carry_keys = [i.key for i in self._issues if i.key in self._selected]
        target_keys = [i.key for i in self._target_issues]
        valid = set(carry_keys) | set(target_keys)

        kept = [k for k in self._target_order if k in valid]
        kept_set = set(kept)

        # New carries: honour `_sort_issues` for a stable initial position.
        new_carries = [
            issue.key
            for issue in self._sort_issues(
                [i for i in self._issues if i.key in self._selected and i.key not in kept_set]
            )
        ]
        # New target rows (post-refresh discovery): pin to the end.
        new_targets = [
            issue.key
            for issue in self._sort_issues(
                [i for i in self._target_issues if i.key not in kept_set and i.key not in new_carries]
            )
        ]

        self._target_order = new_carries + kept + new_targets

    def _sort_issues(self, issues: list[Issue]) -> list[Issue]:
        """Order issues so rollover-status ones cluster at the top of the table."""
        cfg = self.app.cfg  # type: ignore[attr-defined]
        rollover_statuses = list(cfg.rollover.statuses)
        status_rank = {s: i for i, s in enumerate(rollover_statuses)}

        def key(issue: Issue) -> tuple[int, str, str]:
            rank = status_rank.get(issue.status or "", len(rollover_statuses))
            return (rank, issue.status or "", issue.key)

        return sorted(issues, key=key)

    def _render_source_panel(self) -> None:
        assert self._source is not None
        header = self.query_one("#source-header", Static)
        state = (self._source.state or "").capitalize()
        header.update(
            Text.assemble(
                ("Source: ", "dim"),
                (self._source.name, "bold"),
                ("  ·  ", "dim"),
                (state, "dim"),
            )
        )

        table = self.query_one("#source-table", DataTable)
        prev_key = self._cursor_key()
        table.clear()
        selected_style = Style(bold=True)
        muted_style = Style(color="grey54")
        for issue in self._sort_issues(self._issues):
            is_selected = issue.key in self._selected
            mark = "✓" if is_selected else " "
            style = selected_style if is_selected else muted_style
            sp = _format_sp_with_reduction(
                issue.story_points, self._reductions.get(issue.key, 0.0)
            )
            table.add_row(
                Text(mark, style=style),
                Text(issue.key, style=style),
                Text(issue.status or "—", style=style),
                Text(sp, style=style),
                Text((issue.summary or "").strip() or "—", style=style),
                key=issue.key,
            )
        # Preserve cursor across the clear+rebuild so space/e don't warp the user to row 0.
        if prev_key is not None and table.row_count:
            try:
                row_idx = table.get_row_index(prev_key)
            except KeyError:
                row_idx = None
            if row_idx is not None:
                table.move_cursor(row=row_idx, animate=False)

    def _render_target_panel(self) -> None:
        assert self._resolution is not None
        header = self.query_one("#target-header", Static)
        table = self.query_one("#target-table", DataTable)
        prev_cursor = self._target_cursor_key()
        table.clear()

        if self._resolution.target is None:
            header.update(
                Text.assemble(
                    ("Target: ", "dim"),
                    (
                        self._resolution.predicted_name or "?",
                        Style(color="orange3", bold=True),
                    ),
                    ("  ·  ", "dim"),
                    (
                        self._resolution.reason or "No target sprint resolved.",
                        Style(color="orange3"),
                    ),
                )
            )
            return

        target = self._resolution.target
        header.update(
            Text.assemble(
                ("Target: ", "dim"),
                (target.name, "bold"),
                ("  ·  ", "dim"),
                ((target.state or "").capitalize(), "dim"),
                ("  ·  ", "dim"),
                ("PgUp/PgDn · reorder", Style(color="grey54", italic=True)),
            )
        )

        base_style = Style(color="grey62")
        carry_style = Style(color="cyan", bold=True)
        source_by_key = {i.key: i for i in self._issues}
        target_by_key = {i.key: i for i in self._target_issues}
        for key in self._target_order:
            is_carry = key in self._selected
            issue = source_by_key.get(key) if is_carry else target_by_key.get(key)
            if issue is None:
                # Reconciliation should have dropped stale keys, but guard so a
                # transient inconsistency never crashes the render.
                continue
            style = carry_style if is_carry else base_style
            marker = "→" if is_carry else " "
            sp = (
                _format_sp_with_reduction(
                    issue.story_points, self._reductions.get(issue.key, 0.0)
                )
                if is_carry
                else _format_sp(issue.story_points)
            )
            table.add_row(
                Text(marker, style=style),
                Text(issue.key, style=style),
                Text(issue.status or "—", style=style),
                Text(sp, style=style),
                Text((issue.summary or "").strip() or "—", style=style),
                key=key,
            )

        # Preserve the cursor across the clear+rebuild — otherwise every rerender
        # (including a PgUp/PgDn swap) warps the focus back to row 0. `get_row_index`
        # raises `RowDoesNotExist` for a key that vanished from the panel; guard on
        # `_target_order` membership so we only look up keys we actually rendered.
        if (
            prev_cursor is not None
            and table.row_count
            and prev_cursor in self._target_order
        ):
            table.move_cursor(row=table.get_row_index(prev_cursor), animate=False)

    def _render_totals_strip(self) -> None:
        cfg = self.app.cfg  # type: ignore[attr-defined]
        tracked = list(cfg.skills.totals)
        source_totals = compute_totals(self._issues, tracked)

        self.query_one("#totals-active", Static).update(
            _format_totals_line("Active", source_totals, tracked)
        )

        if self._resolution and self._resolution.target is not None:
            base = compute_totals(self._target_issues, tracked)
            carried = [i for i in self._issues if i.key in self._selected]
            projected = carryover_totals(base, carried, self._reductions, tracked)
            self.query_one("#totals-future", Static).update(
                _format_split_totals_line("Future", base, projected, tracked)
            )
        else:
            self.query_one("#totals-future", Static).update(
                Text("Future: — unresolved target sprint", style=Style(color="orange3"))
            )

    # ---- actions ----

    def action_toggle_selection(self) -> None:
        if self._target_has_focus():
            self.app.bell()
            self._set_status(
                "Selection toggles from the source panel. "
                "Focus source (left) and try again."
            )
            return
        key = self._cursor_key()
        if key is None:
            return
        if key in self._selected:
            self._selected.remove(key)
        else:
            self._selected.add(key)
        self._reconcile_target_order()
        self._render_source_panel()
        self._render_target_panel()
        self._render_totals_strip()
        self._set_status(self._status_text())

    def action_select_all(self) -> None:
        cfg = self.app.cfg  # type: ignore[attr-defined]
        rollover_statuses = set(cfg.rollover.statuses)
        self._selected = {
            issue.key for issue in self._issues
            if issue.status in rollover_statuses
        }
        self._reconcile_target_order()
        self._render_source_panel()
        self._render_target_panel()
        self._render_totals_strip()
        self._set_status(self._status_text())

    def action_select_none(self) -> None:
        self._selected.clear()
        self._reconcile_target_order()
        self._render_source_panel()
        self._render_target_panel()
        self._render_totals_strip()
        self._set_status(self._status_text())

    def action_move_or_page_up(self) -> None:
        """PgUp dispatch: reorder on target focus, page-scroll on source focus."""
        if self._target_has_focus():
            self._swap_target_row(-1)
        else:
            self.query_one("#source-table", DataTable).action_page_up()

    def action_move_or_page_down(self) -> None:
        """PgDn dispatch: reorder on target focus, page-scroll on source focus."""
        if self._target_has_focus():
            self._swap_target_row(+1)
        else:
            self.query_one("#source-table", DataTable).action_page_down()

    def _swap_target_row(self, direction: int) -> None:
        """Swap the target-panel cursor row with its neighbour in `_target_order`.

        `direction` is -1 (up) or +1 (down). Out-of-bounds swaps ring the bell
        and leave the order untouched.
        """
        key = self._target_cursor_key()
        if key is None or key not in self._target_order:
            return
        idx = self._target_order.index(key)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._target_order):
            self.app.bell()
            return
        self._target_order[idx], self._target_order[new_idx] = (
            self._target_order[new_idx],
            self._target_order[idx],
        )
        # Rerender then move the cursor to the row the swapped key now sits on
        # so successive PgUp/PgDn presses keep dragging the same row.
        self._render_target_panel()
        table = self.query_one("#target-table", DataTable)
        if key in self._target_order:
            table.move_cursor(row=table.get_row_index(key), animate=False)

    def action_edit_reduction(self) -> None:
        """Prompt for a per-issue SP reduction on the cursor row (local-only, feeds projected totals)."""
        if self._target_has_focus():
            self.app.bell()
            self._set_status(
                "SP reductions only apply to carry-over issues. "
                "Focus the source panel and try again."
            )
            return
        key = self._cursor_key()
        if key is None:
            return
        issue = next((i for i in self._issues if i.key == key), None)
        if issue is None:
            return
        current = self._reductions.get(key, 0.0)
        modal = ReductionModal(key, current, issue.story_points)

        def after(new: float | None) -> None:
            if new is None:
                return
            if new <= 0:
                self._reductions.pop(key, None)
            else:
                self._reductions[key] = float(new)
            self._render_source_panel()
            self._render_target_panel()
            self._render_totals_strip()
            self._set_status(self._status_text())

        self.app.push_screen(modal, after)

    def action_refresh(self) -> None:
        # Explicit user refresh: reset preselection so the config's rollover
        # statuses re-apply after a JIRA sync brought new issues. Also drops
        # any manual target-panel reorderings — a re-seed follows in reload().
        self._selected.clear()
        self._target_order = []
        self.reload()

    def action_open_preview(self) -> None:
        """Confirmation gate: show a preview modal, then run the rollover on confirm."""
        if self._resolution is None or self._resolution.target is None:
            self.app.bell()
            self._set_status(
                "Cannot roll over: target sprint unresolved. "
                "Create the next sprint in JIRA and refresh."
            )
            return
        if not self._selected:
            self.app.bell()
            self._set_status("Nothing selected — pick at least one issue with `space`.")
            return

        cfg = self.app.cfg  # type: ignore[attr-defined]
        tracked = list(cfg.skills.totals)
        base = compute_totals(self._target_issues, tracked)
        carried = [i for i in self._issues if i.key in self._selected]
        projected = carryover_totals(base, carried, self._reductions, tracked)

        modal = RolloverPreviewModal(
            source_name=self._source.name if self._source else "?",
            target_name=self._resolution.target.name,
            carried_issues=carried,
            existing_target_issues=list(self._target_issues),
            projected_totals=projected,
            tracked_skills=tracked,
        )
        self.app.push_screen(modal, self._on_preview_dismissed)

    def _on_preview_dismissed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self._launch_rollover(from_resume=False)

    def action_resume(self) -> None:
        """Continue an in-flight rollover from wherever the previous try failed."""
        if self._partial_attempt is None:
            self._set_status("No partial rollover to resume.")
            return
        self._launch_rollover(from_resume=True)

    def _launch_rollover(self, *, from_resume: bool) -> None:
        if self._source is None or self._resolution is None or self._resolution.target is None:
            return
        source_id = self._source.id
        source_name = self._source.name
        target_id = self._resolution.target.id
        target_name = self._resolution.target.name
        selected = sorted(self._selected)
        # Snapshot the exact target-panel order; this is what the JIRA rank step
        # will push. Copied so a later user reorder can't mutate the in-flight write.
        target_order = list(self._target_order)
        cfg = self.app.cfg  # type: ignore[attr-defined]

        def do_write(session, client) -> None:
            if not from_resume:
                write_ops.start_rollover(
                    session,
                    source_sprint_id=source_id,
                    target_sprint_id=target_id,
                    selected_keys=selected,
                    target_order_keys=target_order,
                )
            write_ops.execute_rollover(
                client,
                session,
                source_sprint_id=source_id,
                source_sprint_name=source_name,
                target_sprint_name=target_name,
                cfg=cfg,
            )

        label = "Rollover resume" if from_resume else "Rollover"
        self.app.run_write(label, do_write, on_done=self.reload)  # type: ignore[attr-defined]
        self._set_status(f"{label} in progress…")

    # ---- helpers ----

    def _cursor_key(self) -> str | None:
        """The source-table row key currently under the cursor."""
        table = self.query_one("#source-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key.value is not None else None

    def _target_cursor_key(self) -> str | None:
        """The target-table row key currently under the cursor."""
        table = self.query_one("#target-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key.value is not None else None

    def _target_has_focus(self) -> bool:
        """True when the target table currently owns focus.

        Selection toggles and SP edits bail on this because those actions belong
        to the source panel; the target panel only accepts cursor movement and
        the PgUp/PgDn reorder pair.
        """
        focused = self.focused
        return focused is not None and getattr(focused, "id", None) == "target-table"

    def _status_text(self) -> str:
        n_selected = len(self._selected)
        n_total = len(self._issues)
        if self._partial_attempt is not None:
            step = self._partial_attempt.completed_step or "not started"
            err = self._partial_attempt.error
            suffix = f" · last error: {err}" if err else ""
            return (
                f"⚠ partial rollover detected — last completed step: {step}. "
                f"Press `Shift+R` to resume{suffix}"
            )
        if self._resolution and self._resolution.target is None:
            return (
                f"{n_selected}/{n_total} selected · target sprint unresolved — "
                f"rollover disabled"
            )
        return (
            f"{n_selected}/{n_total} selected · `c` preview & confirm · "
            f"`space` toggle · `e` edit SP · `a` reselect · `n` clear · "
            f"target PgUp/PgDn reorder · `r` refresh"
        )

    def _set_status(self, text: str) -> None:
        self.query_one("#rollover-status", Static).update(text)


def _format_sp(value: float | None) -> str:
    if value is None:
        return "—"
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _format_sp_with_reduction(value: float | None, reduction: float) -> str:
    """`13` when no reduction; `13→10` when the user reduced by 3."""
    if value is None:
        return "—"
    if reduction <= 0:
        return _format_sp(value)
    remaining = max(0.0, value - reduction)
    return f"{_format_sp(value)}→{_format_sp(remaining)}"


def _skill_abbr(skill: str) -> str:
    """First two letters, uppercased. `Backend` → `BE`, `Framework Dev` → `FR`."""
    trimmed = skill.strip()
    return (trimmed[:2] or "??").upper()


def _format_totals_line(
    label: str,
    totals: SprintTotals,
    tracked_skills: list[str],
) -> Text:
    """Build `{label}: {total}SP | {active}SP | BE: {be}SP | FE: {fe}SP`."""
    active = totals.to_do + totals.in_progress
    parts: list[str] = [
        f"{label}: {_format_sp(totals.total)}SP",
        f"{_format_sp(active)}SP",
    ]
    for skill in tracked_skills:
        value = totals.per_skill.get(skill, 0.0)
        parts.append(f"{_skill_abbr(skill)}: {_format_sp(value)}SP")
    return _compose_totals_line(parts)


def _format_split_totals_line(
    label: str,
    base: SprintTotals,
    projected: SprintTotals,
    tracked_skills: list[str],
) -> Text:
    """Same layout as `_format_totals_line`, but every number is split as `{base}+{delta}SP`.

    `delta = projected - base` per bucket. A zero delta still renders as `+0`
    so the line reads uniformly whether or not carry-overs are selected.
    """
    base_active = base.to_do + base.in_progress
    proj_active = projected.to_do + projected.in_progress
    parts: list[str] = [
        f"{label}: {_format_sp(base.total)}+{_format_sp(projected.total - base.total)}SP",
        f"{_format_sp(base_active)}+{_format_sp(proj_active - base_active)}SP",
    ]
    for skill in tracked_skills:
        base_v = base.per_skill.get(skill, 0.0)
        proj_v = projected.per_skill.get(skill, 0.0)
        parts.append(
            f"{_skill_abbr(skill)}: {_format_sp(base_v)}+{_format_sp(proj_v - base_v)}SP"
        )
    return _compose_totals_line(parts)


def _compose_totals_line(parts: list[str]) -> Text:
    """Assemble segmented totals into a Text with the label bold and `|` separators dimmed."""
    text = Text()
    for i, part in enumerate(parts):
        if i > 0:
            text.append("  |  ", style="dim")
        # First segment (label + total) takes the accent; remaining are plain.
        if i == 0:
            colon = part.find(":")
            text.append(part[: colon + 1] + " ", style="bold")
            text.append(part[colon + 2 :])
        else:
            text.append(part)
    return text
