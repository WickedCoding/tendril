from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static, TabbedContent, TabPane

from sqlalchemy import select

from tendril.db.models import Comment, Issue, IssueLink
from tendril.jira.dto import adf_to_text


class IssueDetailScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh_issue", "Refresh from JIRA"),
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
                yield Static("", id="links-body")
        yield Footer()

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        with self.app.session_factory() as session:  # type: ignore[attr-defined]
            issue = session.get(Issue, self.issue_key)
            if issue is None:
                self.query_one("#title", Label).update(f"[red]{self.issue_key} not in cache[/red]")
                self.query_one("#description-body", Static).update(
                    "Run `tendril sync issue {key}` from the shell.".format(key=self.issue_key)
                )
                return

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
            self.query_one("#links-body", Static).update(_format_links(links))

    def action_refresh_issue(self) -> None:
        self.app.run_issue_refresh(self.issue_key, on_done=self.reload)  # type: ignore[attr-defined]


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


def _format_links(links: list[IssueLink]) -> str:
    if not links:
        return "[no links]"
    lines = []
    for link in links:
        arrow = "→" if link.direction == "outward" else "←"
        lines.append(f"  {link.link_type:<15} {arrow} {link.target_key}")
    return "\n".join(lines)
