from __future__ import annotations

from typing import Callable

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from sqlalchemy.orm import Session

from tendril import config as cfg_mod
from tendril.alerts import ops as alert_ops
from tendril.config import Config, ConfigError, FieldsConfig, JiraConfig, LinksConfig, SyncConfig
from tendril.db.engine import build_engine, session_factory
from tendril.db.models import Comment, Issue, IssueLink
from tendril.db.schema import init_schema
from tendril.jira import client as jira_client
from tendril.sync import commands as sync_ops
from tendril.text import plural

app = typer.Typer(help="tendril — a keyboard-driven JIRA companion.")
config_app = typer.Typer(help="Manage tendril configuration.", no_args_is_help=True)
sync_app = typer.Typer(help="Sync from JIRA to the local cache.", no_args_is_help=True)
watchlist_app = typer.Typer(help="Manage the curated issue watchlist.", no_args_is_help=True)
tag_app = typer.Typer(help="Manage local tags on cached issues (never pushed to JIRA).", no_args_is_help=True)
alert_app = typer.Typer(help="Manage local alerts — mark issues to surface on tag overlap.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(sync_app, name="sync")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(tag_app, name="tag")
app.add_typer(alert_app, name="alert")

console = Console()
err_console = Console(stderr=True)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Launch the TUI when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = _load_config_or_die()
    from tendril.tui.app import TendrilApp
    TendrilApp(cfg).run()


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
    try:
        cfg_mod.set_token(email, token)
    except ConfigError as e:
        err_console.print(f"[red]{e}[/red]")
        err_console.print(f"[dim]Config file at {path} was still written.[/dim]")
        raise typer.Exit(1)
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
    try:
        client = jira_client.build(cfg)
    except ConfigError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    try:
        me = jira_client.myself(client)
    except Exception as e:
        err_console.print(f"[red]JIRA request failed:[/red] {e}")
        raise typer.Exit(2)

    account_id = me.get("accountId")
    if account_id and cfg.jira.account_id != account_id:
        cfg.jira.account_id = account_id
        cfg_mod.save(cfg)

    console.print(f"[green]{me.get('displayName', '?')}[/green] <{me.get('emailAddress', '?')}>")
    console.print(f"accountId: {account_id or '?'}")
    console.print(f"timezone:  {me.get('timeZone', '?')}")


@sync_app.command("issue")
def sync_issue_cmd(
    keys: list[str] = typer.Argument(..., help="One or more JIRA issue keys."),
) -> None:
    """Fetch one or more JIRA issues and upsert them into the local cache.

    Each key is synced independently — a failure on one key logs the error
    and the batch continues. Exit code is 2 if any key failed.
    """
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    failures = 0
    try:
        for key in keys:
            try:
                row = sync_ops.sync_issue(client, session, key, cfg=cfg)
            except Exception as e:
                err_console.print(f"[red]Sync failed[/red] for {key}: {e}")
                failures += 1
                continue
            if row.key != key:
                console.print(
                    f"[yellow]Note:[/yellow] {key} has been moved to [bold]{row.key}[/bold]. "
                    "Watchlist entry migrated."
                )
            console.print(f"[green]Synced[/green] {row.key} — {row.summary}")
    finally:
        close()

    if failures:
        err_console.print(f"[red]{plural(failures, 'issue')} failed to sync.[/red]")
        raise typer.Exit(2)


@sync_app.command("project")
def sync_project_cmd(
    project_keys: list[str] = typer.Argument(..., help="One or more JIRA project keys."),
) -> None:
    """Fetch every issue in one or more JIRA projects into the local cache.

    Each project is synced independently — a failure on one project logs the
    error and the batch continues. Exit code is 2 if any project failed.
    """
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    failures = 0
    try:
        for project_key in project_keys:
            console.print(f"[dim]Syncing project[/dim] [bold]{project_key}[/bold]…")
            try:
                rows = sync_ops.sync_project(client, session, project_key, cfg=cfg)
            except Exception as e:
                err_console.print(f"[red]Sync failed[/red] for {project_key}: {e}")
                failures += 1
                continue
            console.print(
                f"[green]Synced[/green] {plural(len(rows), 'issue')} from project [bold]{project_key}[/bold]."
            )
    finally:
        close()

    if failures:
        err_console.print(f"[red]{plural(failures, 'project')} failed to sync.[/red]")
        raise typer.Exit(2)


@sync_app.command("incremental")
def sync_incremental_cmd() -> None:
    """Refetch issues updated since the last incremental sync, across all previously synced projects."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    try:
        rows = sync_ops.incremental_sync(client, session, cfg=cfg)
        if not rows:
            console.print(
                "[dim]Nothing to sync. Run `tendril sync project KEY` at least once first.[/dim]"
            )
            return
        console.print(f"[green]Synced[/green] {plural(len(rows), 'changed issue')}.")
    except Exception as e:
        err_console.print(f"[red]Sync failed:[/red] {e}")
        raise typer.Exit(2)
    finally:
        close()


@sync_app.command("link-types")
def sync_link_types_cmd() -> None:
    """Fetch the JIRA instance's issue link types and replace the local cache."""
    cfg = _load_config_or_die()
    client = jira_client.build(cfg)
    session, close = _open_session()
    try:
        rows = sync_ops.sync_link_types(client, session)
        console.print(f"[green]Synced[/green] {plural(len(rows), 'link type')}.")
        for r in rows:
            console.print(f"  [bold]{r.name}[/bold] · {r.outward} · {r.inward}")
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
        console.print(f"[green]Watchlist size:[/green] {plural(len(entries), 'entry', 'entries')} after add.")
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
        console.print(f"[green]Removed[/green] {plural(n, 'entry', 'entries')}.")
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
        console.print(f"\n[dim]{plural(link_count, 'link')}, {plural(comment_count, 'comment')}[/dim]")
    finally:
        close()


@tag_app.command("add")
def tag_add_cmd(
    key: str = typer.Argument(..., help="JIRA issue key."),
    tags: list[str] = typer.Argument(..., help="One or more tags to add."),
) -> None:
    """Add tags to a cached issue (idempotent). Tags are local — never pushed to JIRA."""
    session, close = _open_session()
    try:
        rows = alert_ops.add_tags(session, key, tags)
        console.print(
            f"[green]{key}[/green] now has {plural(len(rows), 'tag')}: "
            + (", ".join(sorted(r.tag for r in rows)) or "[dim]none[/dim]")
        )
    finally:
        close()


@tag_app.command("remove")
def tag_remove_cmd(
    key: str = typer.Argument(..., help="JIRA issue key."),
    tags: list[str] = typer.Argument(..., help="One or more tags to remove."),
) -> None:
    """Remove tags from a cached issue."""
    session, close = _open_session()
    try:
        n = alert_ops.remove_tags(session, key, tags)
        console.print(f"[green]Removed[/green] {plural(n, 'tag')} from {key}.")
    finally:
        close()


@tag_app.command("set")
def tag_set_cmd(
    key: str = typer.Argument(..., help="JIRA issue key."),
    tags: list[str] = typer.Argument(None, help="Tags to assign. Omit to clear all tags."),
) -> None:
    """Replace the full tag set for an issue. The bulk-write an LLM would use."""
    session, close = _open_session()
    try:
        rows = alert_ops.set_tags(session, key, tags or [])
        if rows:
            console.print(
                f"[green]{key}[/green] tags set to: "
                + ", ".join(sorted(r.tag for r in rows))
            )
        else:
            console.print(f"[green]Cleared[/green] all tags on {key}.")
    finally:
        close()


@tag_app.command("list")
def tag_list_cmd(
    key: str | None = typer.Argument(None, help="Limit to one issue key. Omit to list all tagged issues."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List tagged issues. `--json` for machine consumption (LLM pipelines)."""
    import json as _json

    session, close = _open_session()
    try:
        if key:
            tags = alert_ops.list_tags_for(session, key)
            if json_out:
                console.print_json(_json.dumps({key: tags}))
                return
            if not tags:
                console.print(f"[dim]{key} has no tags.[/dim]")
                return
            console.print(f"[bold]{key}[/bold]: {', '.join(tags)}")
            return

        pairs = alert_ops.list_all_tagged(session)
        if json_out:
            console.print_json(_json.dumps({k: t for k, t in pairs}))
            return
        if not pairs:
            console.print("[dim]No tagged issues.[/dim]")
            return
        table = Table(title="Tagged issues")
        table.add_column("key")
        table.add_column("tags")
        for k, tags in pairs:
            table.add_row(k, ", ".join(tags))
        console.print(table)
    finally:
        close()


@alert_app.command("add")
def alert_add_cmd(key: str = typer.Argument(..., help="JIRA issue key to mark as an alert.")) -> None:
    """Mark an issue as an alert. It will surface when another cached issue shares any of its tags."""
    session, close = _open_session()
    try:
        alert_ops.mark_alert(session, key)
        tags = alert_ops.list_tags_for(session, key)
        if tags:
            console.print(f"[green]{key}[/green] is now an alert (tags: {', '.join(tags)}).")
        else:
            console.print(
                f"[green]{key}[/green] is now an alert. "
                f"[yellow]It has no tags yet — nothing will surface until you tag it "
                f"with `tendril tag add {key} TAG`.[/yellow]"
            )
    finally:
        close()


@alert_app.command("remove")
def alert_remove_cmd(key: str = typer.Argument(..., help="JIRA issue key to un-alert.")) -> None:
    """Remove the alert marker. The issue's tags are left alone."""
    session, close = _open_session()
    try:
        removed = alert_ops.unmark_alert(session, key)
        if removed:
            console.print(f"[green]Removed[/green] alert marker from {key}.")
        else:
            console.print(f"[dim]{key} was not an alert.[/dim]")
    finally:
        close()


@alert_app.command("list")
def alert_list_cmd() -> None:
    """List every issue marked as an alert, with its tags."""
    session, close = _open_session()
    try:
        alerts = alert_ops.list_alerts(session)
        if not alerts:
            console.print("[dim]No alerts.[/dim]")
            return
        table = Table(title="Alerts")
        table.add_column("key")
        table.add_column("tags")
        table.add_column("since")
        for a in alerts:
            tags = alert_ops.list_tags_for(session, a.issue_key)
            table.add_row(
                a.issue_key,
                ", ".join(tags) if tags else "[yellow]— (won't fire)[/yellow]",
                str(a.created_at),
            )
        console.print(table)
    finally:
        close()


if __name__ == "__main__":
    app()
