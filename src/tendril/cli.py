from __future__ import annotations

from typing import Callable

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from sqlalchemy.orm import Session

from tendril import config as cfg_mod
from tendril.config import Config, ConfigError, FieldsConfig, JiraConfig, LinksConfig, SyncConfig
from tendril.db.engine import build_engine, session_factory
from tendril.db.models import Comment, Issue, IssueLink
from tendril.db.schema import init_schema
from tendril.jira import client as jira_client
from tendril.sync import commands as sync_ops

app = typer.Typer(help="tendril — a keyboard-driven JIRA companion.", no_args_is_help=True)
config_app = typer.Typer(help="Manage tendril configuration.", no_args_is_help=True)
sync_app = typer.Typer(help="Sync from JIRA to the local cache.", no_args_is_help=True)
watchlist_app = typer.Typer(help="Manage the curated issue watchlist.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(sync_app, name="sync")
app.add_typer(watchlist_app, name="watchlist")

console = Console()
err_console = Console(stderr=True)


def _load_config_or_die() -> Config:
    try:
        return cfg_mod.load()
    except ConfigError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _open_session() -> tuple[Session, Callable[[], None]]:
    engine = build_engine()
    init_schema(engine)
    Factory = session_factory(engine)
    session = Factory()
    return session, lambda: session.close()


@config_app.command("init")
def config_init() -> None:
    """Interactively write ~/.config/tendril/config.toml and store the API token."""
    console.print("[bold]tendril config[/bold] — first-time setup")
    url = Prompt.ask("JIRA URL (e.g. https://acme.atlassian.net)").rstrip("/")
    email = Prompt.ask("Your Atlassian email")
    token = Prompt.ask("API token (create at id.atlassian.com)", password=True)

    cfg = Config(
        jira=JiraConfig(url=url, email=email),
        fields=FieldsConfig(),
        links=LinksConfig(),
        sync=SyncConfig(),
    )
    path = cfg_mod.save(cfg)
    cfg_mod.set_token(email, token)
    console.print(f"[green]Wrote[/green] {path}")
    console.print(f"[green]Stored token in keyring[/green] (service={cfg_mod.KEYRING_SERVICE}, user={email})")
    console.print("Try: [cyan]tendril whoami[/cyan]")


@config_app.command("show")
def config_show() -> None:
    """Print the current configuration (token is never printed)."""
    try:
        cfg = cfg_mod.load()
    except ConfigError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"config file: {cfg_mod.config_path()}")
    console.print(f"data dir:    {cfg_mod.data_dir()}")
    console.print(f"[bold]jira[/bold]   url={cfg.jira.url}  email={cfg.jira.email}")
    console.print(f"[bold]fields[/bold] feature_flags={cfg.fields.feature_flags}  sprint={cfg.fields.sprint}")
    console.print(f"[bold]links[/bold]  default_link_type={cfg.links.default_link_type}")


@app.command()
def whoami() -> None:
    """Fetch and display the current JIRA user (verifies auth)."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    try:
        me = jira_client.myself(client)
    except Exception as e:
        err_console.print(f"[red]JIRA request failed:[/red] {e}")
        raise typer.Exit(2)

    console.print(f"[green]{me.get('displayName', '?')}[/green] <{me.get('emailAddress', '?')}>")
    console.print(f"accountId: {me.get('accountId', '?')}")
    console.print(f"timezone:  {me.get('timeZone', '?')}")


@sync_app.command("issue")
def sync_issue_cmd(key: str) -> None:
    """Fetch a single JIRA issue and upsert it into the local cache."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    try:
        row = sync_ops.sync_issue(client, session, key)
        console.print(f"[green]Synced[/green] {row.key} — {row.summary}")
    except Exception as e:
        err_console.print(f"[red]Sync failed:[/red] {e}")
        raise typer.Exit(2)
    finally:
        close()


@sync_app.command("project")
def sync_project_cmd(project_key: str) -> None:
    """Fetch every issue in a JIRA project into the local cache."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    try:
        rows = sync_ops.sync_project(client, session, project_key)
        console.print(f"[green]Synced[/green] {len(rows)} issue(s) from project [bold]{project_key}[/bold].")
    except Exception as e:
        err_console.print(f"[red]Sync failed:[/red] {e}")
        raise typer.Exit(2)
    finally:
        close()


@sync_app.command("incremental")
def sync_incremental_cmd() -> None:
    """Refetch issues updated since the last incremental sync, across all previously synced projects."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    try:
        rows = sync_ops.incremental_sync(client, session)
        if not rows:
            console.print(
                "[dim]Nothing to sync. Run `tendril sync project KEY` at least once first.[/dim]"
            )
            return
        console.print(f"[green]Synced[/green] {len(rows)} changed issue(s).")
    except Exception as e:
        err_console.print(f"[red]Sync failed:[/red] {e}")
        raise typer.Exit(2)
    finally:
        close()


@watchlist_app.command("add")
def watchlist_add_cmd(
    keys: list[str] = typer.Argument(..., help="One or more JIRA issue keys."),
    note: str | None = typer.Option(None, "--note", "-n", help="Optional note attached to each entry."),
) -> None:
    """Add issue keys to the watchlist (idempotent).

    Does not fetch from JIRA. If a key isn't in the local cache yet, sync the
    project (`tendril sync project KEY`) or the single issue (`tendril sync issue KEY`).
    """
    session, close = _open_session()
    try:
        entries, uncached = sync_ops.add_to_watchlist(session, keys, note=note)
        console.print(f"[green]Watchlist size:[/green] {len(entries)} entry/entries after add.")
        if uncached:
            console.print(
                f"[yellow]Not yet in cache:[/yellow] {', '.join(uncached)}\n"
                "[dim]Run `tendril sync project KEY` or `tendril sync issue KEY` to populate.[/dim]"
            )
    finally:
        close()


@watchlist_app.command("remove")
def watchlist_remove_cmd(
    keys: list[str] = typer.Argument(..., help="One or more JIRA issue keys."),
) -> None:
    """Remove issue keys from the watchlist. The cached issue rows are left alone."""
    session, close = _open_session()
    try:
        n = sync_ops.remove_from_watchlist(session, keys)
        console.print(f"[green]Removed[/green] {n} entry/entries.")
    finally:
        close()


@watchlist_app.command("list")
def watchlist_list_cmd() -> None:
    """Print the watchlist with cached issue metadata (run `sync watchlist` to populate)."""
    session, close = _open_session()
    try:
        entries = sync_ops.list_watchlist(session)
        if not entries:
            console.print("[dim]Watchlist is empty.[/dim]")
            return
        table = Table(title="Watchlist")
        table.add_column("key")
        table.add_column("status")
        table.add_column("summary")
        table.add_column("updated")
        table.add_column("note")
        for entry, issue in entries:
            table.add_row(
                entry.issue_key,
                (issue.status if issue else "[dim]-not synced-[/dim]") or "-",
                (issue.summary if issue else "") or "",
                str(issue.updated) if issue and issue.updated else "-",
                entry.note or "",
            )
        console.print(table)
    finally:
        close()


@app.command()
def show(key: str) -> None:
    """Print an issue from the local cache."""
    session, close = _open_session()
    try:
        issue = session.get(Issue, key)
        if issue is None:
            err_console.print(f"[yellow]{key} not in local cache. Run `tendril sync issue {key}` first.[/yellow]")
            raise typer.Exit(1)

        table = Table(show_header=False, box=None)
        table.add_row("[bold]key[/bold]", issue.key)
        table.add_row("[bold]summary[/bold]", issue.summary or "")
        table.add_row("[bold]status[/bold]", issue.status or "")
        table.add_row("[bold]type[/bold]", issue.issuetype or "")
        table.add_row("[bold]assignee[/bold]", issue.assignee_account_id or "-")
        table.add_row("[bold]reporter[/bold]", issue.reporter_account_id or "-")
        table.add_row("[bold]created[/bold]", str(issue.created) if issue.created else "-")
        table.add_row("[bold]updated[/bold]", str(issue.updated) if issue.updated else "-")
        table.add_row("[bold]duedate[/bold]", str(issue.duedate) if issue.duedate else "-")
        table.add_row("[bold]parent[/bold]", issue.parent_key or "-")
        table.add_row("[bold]synced[/bold]", str(issue.last_synced_at))
        console.print(table)

        link_count = session.query(IssueLink).filter(IssueLink.source_key == key).count()
        comment_count = session.query(Comment).filter(Comment.issue_key == key).count()
        console.print(f"\n[dim]{link_count} link(s), {comment_count} comment(s)[/dim]")
    finally:
        close()


if __name__ == "__main__":
    app()
