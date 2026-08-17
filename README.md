# tendril

A keyboard-driven JIRA companion. A local SQLite cache mirrors whole JIRA projects; a Textual TUI browses them offline; a small set of write operations (comment, link, feature-flags) lets you push back without leaving the terminal.

Deliberately narrow: this is a personal tool, not a team dashboard.

## Install

```sh
uv sync
uv run tendril config init          # walks through URL, email, API token
uv run tendril whoami               # verifies auth
```

Config lives at `~/.config/tendril/config.toml`. The API token is stored in the OS keyring under service `tendril`, keyed by your email. The local cache is a SQLite database at `~/.local/share/tendril/tendril.db`.

## First sync

```sh
uv run tendril sync project MMINT   # pulls every issue in MMINT into the cache (paginated)
uv run tendril show MMINT-42        # prints an issue from the cache
```

After the first `sync project`, `sync incremental` will refresh only issues that changed:

```sh
uv run tendril sync incremental     # refreshes every project you've synced before
```

## Watchlist

The watchlist is a marker layer on top of the cache. Adding a key never touches JIRA. If the key isn't in the cache yet, the CLI tells you.

```sh
uv run tendril watchlist add MMINT-42 MMINT-100
uv run tendril watchlist list
uv run tendril watchlist remove MMINT-42
```

## TUI

Run with no subcommand:

```sh
uv run tendril
```

Two screens:

**Watchlist** — a table of watched issues.

| key | binding                    |
|-----|----------------------------|
| a   | add issue key to watchlist |
| d   | remove highlighted row     |
| s   | run incremental sync       |
| r   | reload from cache          |
| ↵   | open issue detail          |
| q   | quit                       |

**Issue detail** — metadata plus tabs (Description, Comments, Links, Flags).

| key | binding                                       |
|-----|-----------------------------------------------|
| r   | refetch this issue from JIRA                  |
| c   | add a comment (ctrl+s in the modal to submit) |
| l   | link this issue to another key                |
| x   | remove the highlighted link (Links tab only)  |
| f   | edit the feature-flags custom field           |
| esc | back                                          |

**Command palette** — `ctrl+p` opens Textual's palette. It includes:

- `Sync project…` — prompts for a project key.
- `Sync project KEY` — one entry per project already synced.

## Feature flags

The `f` binding is only useful once you tell tendril the custom-field id for feature flags. Find it, then add it to `~/.config/tendril/config.toml`:

```toml
[fields]
feature_flags = "customfield_10457"
```

The field is assumed to be a JIRA labels-type custom field (payload shape `["flag_a", "flag_b"]`). Empty submit clears all flags.

## Design notes

- **Sync fills the cache; the watchlist is on top.** Two separate tables.
- **Every write refetches the touched issue.** No local mutation bypasses JIRA — the cache stays honest.
- **Whole-project sync only.** Per-issue single fetches exist (`sync issue KEY`) but are a fallback; the intended workflow is `sync project KEY` once, then `sync incremental` from there.
- **JIRA rename resilience.** If JIRA has moved an issue to another project, `sync issue OLDKEY` follows the redirect, cache is upserted under the new key, and any watchlist entry for the old key is migrated.
- **No Alembic yet.** `Base.metadata.create_all()` plus a `schema_version` row carries us here. Alembic joins when the first breaking schema change lands.

## Testing

```sh
uv run pytest
```

Unit + Textual `Pilot` smoke tests. Live integration tests (real JIRA calls against a sandbox) are gated:

```sh
TENDRIL_LIVE=1 TENDRIL_LIVE_ISSUE=SANDBOX-1 uv run pytest tests/integration
```

## Layout

```
src/tendril/
  cli.py            typer app; console_script `tendril`
  config.py         XDG paths, TOML load/save, keyring
  db/               SQLAlchemy 2 models, engine, schema init
  jira/             thin atlassian-python-api wrapper + DTOs
  sync/             fetch → normalize → upsert; sync_issue, sync_project, incremental
  operations/       single write layer (JIRA write → refetch)
  tui/              Textual app, screens, modals, command-palette provider
```
