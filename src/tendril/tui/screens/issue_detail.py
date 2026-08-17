from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static, TabbedContent, TabPane

from sqlalchemy import select

from tendril.db.models import Comment, Issue, IssueLink
from tendril.jira.dto import adf_to_text
from tendril.operations import ops as write_ops
from tendril.tui.screens.comment_modal import CommentModal
from tendril.tui.screens.flags_modal import FlagsModal
from tendril.tui.screens.link_modal import LinkModal


class IssueDetailScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh_issue", "Refresh from JIRA"),
        Binding("c", "add_comment", "Comment"),
        Binding("l", "add_link", "Link"),
        Binding("x", "remove_link", "Remove link"),
        Binding("f", "edit_flags", "Flags"),
        Binding("p", "open_parent", "Parent"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    #meta-panel { height: auto; padding: 1 2; }
    #meta-panel Label { margin-right: 2; }
    TabbedContent { height: 1fr; }
    """

    def __init__(self, issue_key: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self._parent_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="meta-panel"):
            yield Label("", id="title")
            yield Label("", id="meta-line-1")
            yield Label("", id="meta-line-2")
        with TabbedContent(initial="tab-description"):
            with TabPane("Description", id="tab-description"):
                yield Static("", id="description-body", markup=False)
            with TabPane("Comments", id="tab-comments"):
                yield Static("", id="comments-body", markup=False)
            with TabPane("Links", id="tab-links"):
                yield DataTable(id="links-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Flags", id="tab-flags"):
                yield Static("", id="flags-body")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#links-table", DataTable)
        table.add_columns("type", "direction", "target", "title", "status", "jira_link_id")
        self.reload()

    def reload(self) -> None:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            issue = session.get(Issue, self.issue_key)
            if issue is None:
                self._parent_key = None
                self.refresh_bindings()
                self.query_one("#title", Label).update(f"[red]{self.issue_key} not in cache[/red]")
                self.query_one("#description-body", Static).update(
                    f"Run `tendril sync issue {self.issue_key}` from the shell."
                )
                return

            self._parent_key = issue.parent_key
            self.refresh_bindings()

            self.query_one("#title", Label).update(
                f"[bold]{issue.key}[/bold] · {issue.status or '—'} · {issue.issuetype or '—'}\n"
                f"[b]{issue.summary or ''}[/b]"
            )
            self.query_one("#meta-line-1", Label).update(
                f"assignee: {issue.assignee_account_id or '—'}   "
                f"reporter: {issue.reporter_account_id or '—'}   "
                f"parent: {issue.parent_key or '—'}"
            )
            self.query_one("#meta-line-2", Label).update(
                f"created: {issue.created or '—'}   "
                f"updated: {issue.updated or '—'}   "
                f"due: {issue.duedate or '—'}   "
                f"synced: {issue.last_synced_at}"
            )

            desc = _extract_description(issue.raw_json)
            self.query_one("#description-body", Static).update(desc or "[no description]")

            comments = session.scalars(
                select(Comment).where(Comment.issue_key == self.issue_key).order_by(Comment.created)
            ).all()
            self.query_one("#comments-body", Static).update(_format_comments(comments))

            links = session.scalars(
                select(IssueLink).where(IssueLink.source_key == self.issue_key)
            ).all()
            children = session.scalars(
                select(Issue).where(Issue.parent_key == self.issue_key).order_by(Issue.key)
            ).all()

            target_keys = {link.target_key for link in links}
            summaries: dict[str, str | None] = {}
            if target_keys:
                for key, status, summary in session.execute(
                    select(Issue.key, Issue.status, Issue.summary).where(Issue.key.in_(target_keys))
                ):
                    summaries[key] = (summary, status)

            table = self.query_one("#links-table", DataTable)
            table.clear()

            for link in links:
                arrow = "→" if link.direction == "outward" else "←"
                table.add_row(
                    link.link_type, arrow, link.target_key,
                    _title_cell(link.target_key, summaries),
                    _status_cell(link.target_key, summaries),
                    link.jira_link_id,
                    key=f"link:{link.id}",
                )
            for child in children:
                table.add_row(
                    "Child", "↓", child.key,
                    child.summary or "[dim]—[/dim]",
                    child.status or "[dim]-[/dim]",
                    "—",
                    key=f"child:{child.key}",
                )

            self.query_one("#flags-body", Static).update(self._render_flags(issue.raw_json))

    def _render_flags(self, raw_json: dict) -> str:
        field_id = self._flags_field_id()
        if not field_id:
            return "[dim]No feature-flags field configured. Set `fields.feature_flags` in config.toml.[/dim]"
        values = write_ops.read_feature_flags(raw_json, field_id)
        if not values:
            return f"[dim]no flags set[/dim]  ([code]{field_id}[/code])"
        return "  " + "\n  ".join(values) + f"\n\n[dim]field: {field_id}[/dim]"

    def _flags_field_id(self) -> str | None:
        return self.app.cfg.fields.feature_flags  # type: ignore[attr-defined]

    # ---- actions ----

    def action_refresh_issue(self) -> None:
        self.app.run_issue_refresh(self.issue_key, on_done=self.reload)  # type: ignore[attr-defined]

    def action_add_comment(self) -> None:
        def after(body: str | None) -> None:
            if not body:
                return
            self.app.run_write(  # type: ignore[attr-defined]
                "Add comment",
                lambda session, client: write_ops.add_comment(client, session, self.issue_key, body),
                on_done=self.reload,
            )
        self.app.push_screen(CommentModal(), after)

    def action_add_link(self) -> None:
        default = self.app.cfg.links.default_link_type  # type: ignore[attr-defined]

        def after(result: tuple[str, str] | None) -> None:
            if not result:
                return
            target, link_type = result
            self.app.run_write(  # type: ignore[attr-defined]
                f"Link → {target}",
                lambda session, client: write_ops.create_link(
                    client, session, self.issue_key, target, link_type
                ),
                on_done=self.reload,
            )

        self.app.push_screen(LinkModal(default_link_type=default), after)

    def action_remove_link(self) -> None:
        # Only meaningful when the links tab is active AND a real link row is selected.
        tabs = self.query_one(TabbedContent)
        if tabs.active != "tab-links":
            self.app.notify("Switch to the Links tab to remove a link.", severity="warning")
            return
        table = self.query_one("#links-table", DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        raw = str(row_key.value) if row_key.value is not None else ""
        if not raw.startswith("link:"):
            self.app.notify("Child rows aren't real links — nothing to remove.", severity="warning")
            return
        link_id = int(raw.removeprefix("link:"))
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            link = session.get(IssueLink, link_id)
            if link is None:
                return
            jira_link_id = link.jira_link_id
            target = link.target_key
        self.app.run_write(  # type: ignore[attr-defined]
            f"Unlink {target}",
            lambda session, client: write_ops.delete_link(
                client, session, self.issue_key, jira_link_id
            ),
            on_done=self.reload,
        )

    def action_open_parent(self) -> None:
        if not self._parent_key:
            return
        self.app.push_screen(IssueDetailScreen(self._parent_key))

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "open_parent":
            return bool(self._parent_key)
        return True

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        raw = str(event.row_key.value) if event.row_key.value is not None else ""
        target: str | None = None
        if raw.startswith("child:"):
            target = raw.removeprefix("child:")
        elif raw.startswith("link:"):
            link_id = int(raw.removeprefix("link:"))
            with self.app.session_factory() as session:  # type: ignore[attr-defined]
                link = session.get(IssueLink, link_id)
                target = link.target_key if link else None
        if target:
            self.app.push_screen(IssueDetailScreen(target))

    def action_edit_flags(self) -> None:
        field_id = self._flags_field_id()
        if not field_id:
            self.app.notify(
                "No feature-flags field configured. Set fields.feature_flags in config.toml.",
                severity="warning",
            )
            return
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            issue = session.get(Issue, self.issue_key)
            current = write_ops.read_feature_flags(issue.raw_json, field_id) if issue else []

        def after(values: list[str] | None) -> None:
            if values is None:
                return
            self.app.run_write(  # type: ignore[attr-defined]
                "Set flags",
                lambda session, client: write_ops.set_feature_flags(
                    client, session, self.issue_key, field_id, values
                ),
                on_done=self.reload,
            )

        self.app.push_screen(FlagsModal(current), after)


def _title_cell(target_key: str, summaries: dict[str, (str | None, str | None)]) -> str:
    if target_key not in summaries:
        return "[dim]not synced[/dim]"
    return summaries[target_key][0] or "[dim]—[/dim]"

def _status_cell(target_key: str, summaries: dict[str, (str | None, str | None)]) -> str:
    if target_key not in summaries:
        return "[dim]not synced[/dim]"
    return summaries[target_key][1] or "[dim]—[/dim]"

def _extract_description(raw: dict) -> str:
    body = ((raw or {}).get("fields") or {}).get("description")
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return adf_to_text(body)
    return str(body)


def _format_comments(comments: list[Comment]) -> str:
    if not comments:
        return "[no comments]"
    lines: list[str] = []
    for c in comments:
        header = f"— {c.author_account_id or 'unknown'} · {c.created or ''}"
        lines.append(header)
        lines.append(c.body or "")
        lines.append("")
    return "\n".join(lines).rstrip()
