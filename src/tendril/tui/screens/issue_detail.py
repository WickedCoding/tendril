from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from rich.text import Text
from sqlalchemy import select

from tendril.alerts import ops as alert_ops
from tendril.alerts.matcher import find_surfaces
from tendril.db.models import Comment, Issue, IssueLink, LinkType
from tendril.db.users import format_user, resolve_display_names
from tendril.jira.render import render_description
from tendril.operations import ops as write_ops
from tendril.tui.screens.comment_modal import CommentModal
from tendril.tui.screens.flags_modal import FlagsModal
from tendril.tui.screens.link_modal import LinkModal
from tendril.tui.screens.surface_card_modal import SurfaceCardModal
from tendril.tui.screens.tags_modal import TagsModal


class IssueDetailScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh_issue", "Refresh from JIRA"),
        Binding("c", "add_comment", "Comment"),
        Binding("l", "add_link", "Link"),
        Binding("x", "remove_link", "Remove link"),
        Binding("f", "edit_flags", "Flags"),
        Binding("t", "edit_tags", "Tags"),
        Binding("A", "toggle_alert", "Alert on/off"),
        Binding("s", "focus_surfaces", "Surfaces"),
        Binding("m", "toggle_mine_filter", "Mine (links)"),
        Binding("p", "open_parent", "Parent"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    #meta-panel { height: auto; padding: 1 2; }
    #meta-panel Label { margin-right: 2; }
    #detail-body { height: 1fr; }
    #detail-body > TabbedContent { width: 7fr; height: 1fr; }
    #surfaces-panel {
        width: 3fr; height: 1fr;
        padding: 1 1;
        border-left: solid $panel;
    }
    #surfaces-header { color: $text-muted; padding-bottom: 1; }
    #surfaces-empty { color: $text-muted; }
    #surfaces-list { height: 1fr; }
    #links-table { height: 1fr; }
    """

    def __init__(self, issue_key: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self._parent_key: str | None = None
        self._surfaces: list[tuple[Issue, list[str]]] = []
        self._mine_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="meta-panel"):
            yield Label("", id="title")
            yield Label("", id="meta-line-1")
            yield Label("", id="meta-line-2")
        with Horizontal(id="detail-body"):
            with TabbedContent(initial="tab-description"):
                with TabPane("Description", id="tab-description"):
                    yield Static("", id="description-body", markup=False)
                with TabPane("Comments", id="tab-comments"):
                    yield Static("", id="comments-body", markup=False)
                with TabPane("Links", id="tab-links"):
                    yield DataTable(id="links-table", cursor_type="row", zebra_stripes=True)
                with TabPane("Flags", id="tab-flags"):
                    yield Static("", id="flags-body")
            with VerticalScroll(id="surfaces-panel"):
                yield Static("Surfaces", id="surfaces-header")
                yield OptionList(id="surfaces-list")
                yield Static("no surfaces", id="surfaces-empty")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#links-table", DataTable)
        # Fixed column widths so the table fits inside the 7fr detail pane instead of
        # auto-sizing to the widest title and overflowing under the surfaces panel.
        # The row key still carries `link:<id>` / `child:<key>` for remove/navigate.
        table.add_column("linked item", width=35)
        table.add_column("title", width=55)
        table.add_column("status", width=16)
        self.reload()

    def reload(self) -> None:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            issue = session.get(Issue, self.issue_key)
            if issue is None:
                self._parent_key = None
                self._surfaces = []
                self.refresh_bindings()
                self.query_one("#title", Label).update(f"[red]{self.issue_key} not in cache[/red]")
                self.query_one("#description-body", Static).update(
                    f"Run `tendril sync issue {self.issue_key}` from the shell."
                )
                self._render_surfaces_panel([])
                return

            self._parent_key = issue.parent_key
            self.refresh_bindings()

            alert_suffix = " · [yellow]ALERT[/yellow]" if alert_ops.is_alert(session, self.issue_key) else ""
            tags = alert_ops.list_tags_for(session, self.issue_key)
            tag_line = f"   tags: {', '.join('#' + t for t in tags)}" if tags else ""

            self.query_one("#title", Label).update(
                f"[bold]{issue.key}[/bold] · {issue.status or '—'} · {issue.issuetype or '—'}{alert_suffix}\n"
                f"[b]{issue.summary or ''}[/b]"
            )
            meta_names = resolve_display_names(
                session,
                (issue.assignee_account_id, issue.reporter_account_id),
            )
            self.query_one("#meta-line-1", Label).update(
                f"assignee: {format_user(issue.assignee_account_id, meta_names)}   "
                f"reporter: {format_user(issue.reporter_account_id, meta_names)}   "
                f"parent: {issue.parent_key or '—'}"
            )
            self.query_one("#meta-line-2", Label).update(
                f"created: {issue.created or '—'}   "
                f"updated: {issue.updated or '—'}   "
                f"due: {issue.duedate or '—'}   "
                f"synced: {issue.last_synced_at}"
                f"{tag_line}"
            )

            desc = render_description(issue.raw_json)
            self.query_one("#description-body", Static).update(desc if desc is not None else "[no description]")

            comments = session.scalars(
                select(Comment).where(Comment.issue_key == self.issue_key).order_by(Comment.created)
            ).all()
            comment_names = resolve_display_names(
                session, (c.author_account_id for c in comments)
            )
            self.query_one("#comments-body", Static).update(
                _format_comments(comments, comment_names)
            )

            links = session.scalars(
                select(IssueLink).where(IssueLink.source_key == self.issue_key)
            ).all()
            children = session.scalars(
                select(Issue).where(Issue.parent_key == self.issue_key).order_by(Issue.key)
            ).all()

            target_keys = {link.target_key for link in links}
            summaries: dict[str, tuple[str | None, str | None, str | None]] = {}
            if target_keys:
                for key, status, summary, assignee in session.execute(
                    select(
                        Issue.key,
                        Issue.status,
                        Issue.summary,
                        Issue.assignee_account_id,
                    ).where(Issue.key.in_(target_keys))
                ):
                    summaries[key] = (summary, status, assignee)

            link_type_phrases = {
                lt.name: (lt.outward, lt.inward)
                for lt in session.scalars(select(LinkType)).all()
            }

            table = self.query_one("#links-table", DataTable)
            table.clear()

            me = self._me()
            mine_active = self._mine_only and me is not None

            for link in links:
                if mine_active:
                    entry = summaries.get(link.target_key)
                    # Uncached target: we can't know its assignee; hide when filtering to mine.
                    if entry is None or entry[2] != me:
                        continue
                table.add_row(
                    _linked_item_cell(link.link_type, link.direction, link.target_key, link_type_phrases),
                    _title_cell(link.target_key, summaries),
                    _status_cell(link.target_key, summaries),
                    key=f"link:{link.id}",
                )
            for child in children:
                if mine_active and child.assignee_account_id != me:
                    continue
                table.add_row(
                    f"contains {child.key}",
                    child.summary or "[dim]—[/dim]",
                    child.status or "[dim]-[/dim]",
                    key=f"child:{child.key}",
                )

            self.query_one("#flags-body", Static).update(self._render_flags(issue.raw_json))

            self._surfaces = find_surfaces(session, self.issue_key)
            self._render_surfaces_panel(self._surfaces)

    def _render_surfaces_panel(self, surfaces: list[tuple[Issue, list[str]]]) -> None:
        option_list = self.query_one("#surfaces-list", OptionList)
        empty = self.query_one("#surfaces-empty", Static)
        option_list.clear_options()
        if not surfaces:
            option_list.display = False
            empty.display = True
            return
        empty.display = False
        option_list.display = True
        for idx, (issue, shared_tags) in enumerate(surfaces):
            option_list.add_option(Option(_card_prompt(issue, shared_tags), id=str(idx)))

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
        cfg = self.app.cfg  # type: ignore[attr-defined]

        def after(body: str | None) -> None:
            if not body:
                return
            self.app.run_write(  # type: ignore[attr-defined]
                "Add comment",
                lambda session, client: write_ops.add_comment(
                    client, session, self.issue_key, body, cfg=cfg
                ),
                on_done=self.reload,
            )
        self.app.push_screen(CommentModal(), after)

    def action_add_link(self) -> None:
        cfg = self.app.cfg  # type: ignore[attr-defined]
        default = cfg.links.default_link_type
        link_types = self._load_link_types()

        def after(result: tuple[str, str, str] | None) -> None:
            if not result:
                return
            target, type_name, direction = result
            self.app.run_write(  # type: ignore[attr-defined]
                f"Link → {target}",
                lambda session, client: write_ops.create_link(
                    client, session, self.issue_key, target, type_name, direction, cfg=cfg
                ),
                on_done=self.reload,
            )

        self.app.push_screen(LinkModal(link_types, default_link_type=default), after)

    def _load_link_types(self) -> list[LinkType]:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            return list(session.scalars(select(LinkType).order_by(LinkType.name)).all())

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
        cfg = self.app.cfg  # type: ignore[attr-defined]
        self.app.run_write(  # type: ignore[attr-defined]
            f"Unlink {target}",
            lambda session, client: write_ops.delete_link(
                client, session, self.issue_key, jira_link_id, cfg=cfg
            ),
            on_done=self.reload,
        )

    def action_open_parent(self) -> None:
        if not self._parent_key:
            return
        self.app.push_screen(IssueDetailScreen(self._parent_key))

    def action_edit_tags(self) -> None:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            current = alert_ops.list_tags_for(session, self.issue_key)

        def after(values: list[str] | None) -> None:
            if values is None:
                return
            with self.app.session_factory() as session:  # type: ignore[attr-defined]
                alert_ops.set_tags(session, self.issue_key, values)
            self.reload()

        self.app.push_screen(TagsModal(current), after)

    def action_toggle_alert(self) -> None:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            if alert_ops.is_alert(session, self.issue_key):
                alert_ops.unmark_alert(session, self.issue_key)
                self.app.notify(f"{self.issue_key} · alert off")
            else:
                alert_ops.mark_alert(session, self.issue_key)
                tags = alert_ops.list_tags_for(session, self.issue_key)
                if tags:
                    self.app.notify(f"{self.issue_key} · alert on")
                else:
                    self.app.notify(
                        f"{self.issue_key} · alert on — add tags with `t` so it can fire.",
                        severity="warning",
                    )
        self.reload()

    def action_focus_surfaces(self) -> None:
        option_list = self.query_one("#surfaces-list", OptionList)
        if option_list.display:
            option_list.focus()

    def action_toggle_mine_filter(self) -> None:
        if not self._mine_only and self._me() is None:
            self.app.notify(
                'Run `tendril whoami` first to enable "mine" filter.',
                severity="warning",
            )
            return
        self._mine_only = not self._mine_only
        self.app.notify(
            f'Links filter: mine {"on" if self._mine_only else "off"}'
        )
        self.reload()

    def _me(self) -> str | None:
        cfg = getattr(self.app, "cfg", None)
        return getattr(getattr(cfg, "jira", None), "account_id", None)

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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "surfaces-list":
            return
        opt_id = event.option.id
        if opt_id is None:
            return
        try:
            idx = int(opt_id)
        except ValueError:
            return
        if not (0 <= idx < len(self._surfaces)):
            return
        target_issue, shared_tags = self._surfaces[idx]
        default = self.app.cfg.links.default_link_type  # type: ignore[attr-defined]

        source_key = self.issue_key
        target_key = target_issue.key
        cfg = self.app.cfg  # type: ignore[attr-defined]
        link_types = self._load_link_types()

        def after(result: tuple[str, str] | None) -> None:
            if not result:
                return
            type_name, direction = result
            self.app.run_write(  # type: ignore[attr-defined]
                f"Link → {target_key}",
                lambda session, client: write_ops.create_link(
                    client, session, source_key, target_key, type_name, direction, cfg=cfg
                ),
                on_done=self.reload,
            )

        self.app.push_screen(
            SurfaceCardModal(
                target_key=target_key,
                status=target_issue.status,
                summary=target_issue.summary,
                shared_tags=shared_tags,
                link_types=link_types,
                default_link_type=default,
            ),
            after,
        )

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

        cfg = self.app.cfg  # type: ignore[attr-defined]

        def after(values: list[str] | None) -> None:
            if values is None:
                return
            self.app.run_write(  # type: ignore[attr-defined]
                "Set flags",
                lambda session, client: write_ops.set_feature_flags(
                    client, session, self.issue_key, field_id, values, cfg=cfg
                ),
                on_done=self.reload,
            )

        self.app.push_screen(FlagsModal(current), after)


def _card_prompt(issue: Issue, shared_tags: list[str]) -> Text:
    """Rich Text for one surface card: three lines (key+status, summary, shared tags)."""
    header = Text()
    header.append(issue.key, style="bold")
    header.append(f"  ·  {issue.status or '—'}")
    summary = Text((issue.summary or "").strip() or "—")
    summary.truncate(120, overflow="ellipsis")
    tags = Text("shared: " + " · ".join("#" + t for t in shared_tags), style="dim")
    return Text("\n").join([header, summary, tags])


def _linked_item_cell(
    link_type: str,
    direction: str,
    target_key: str,
    phrases: dict[str, tuple[str, str]],
) -> str:
    """Render a link as `<phrase> TARGET-KEY`.

    Uses the cached outward/inward phrase for the link type; falls back to the
    raw API name plus a direction arrow if the type isn't cached (run
    `tendril sync link-types` to fix).
    """
    if link_type in phrases:
        outward, inward = phrases[link_type]
        phrase = outward if direction == "outward" else inward
    else:
        arrow = "→" if direction == "outward" else "←"
        phrase = f"{link_type} {arrow}"
    return f"{phrase} {target_key}"


def _title_cell(target_key: str, summaries: dict[str, tuple[str | None, str | None, str | None]]) -> str:
    if target_key not in summaries:
        return "[dim]not synced[/dim]"
    return summaries[target_key][0] or "[dim]—[/dim]"

def _status_cell(target_key: str, summaries: dict[str, tuple[str | None, str | None, str | None]]) -> str:
    if target_key not in summaries:
        return "[dim]not synced[/dim]"
    return summaries[target_key][1] or "[dim]—[/dim]"

def _format_comments(comments: list[Comment], names: dict[str, str]) -> str:
    if not comments:
        return "[no comments]"
    lines: list[str] = []
    for c in comments:
        author = format_user(c.author_account_id, names) if c.author_account_id else "unknown"
        header = f"— {author} · {c.created or ''}"
        lines.append(header)
        lines.append(c.body or "")
        lines.append("")
    return "\n".join(lines).rstrip()
