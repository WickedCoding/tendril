# tendril

A keyboard-driven JIRA companion. A local SQLite cache mirrors whole JIRA projects; a Textual TUI browses them offline; a small set of write operations (comment, link, feature-flags) lets you push back without leaving the terminal. Local **tags** and **alerts** surface related issues as you browse — the coworker's "logos need light/dark alternatives" issue pops up as a card when you open the PO's "add logo to layout" ticket, ready to link in one keystroke.

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

**Issue detail** — metadata plus tabs (Description, Comments, Links, Flags) on the left, a **Surfaces** panel on the right (7:3 split).

| key | binding                                       |
|-----|-----------------------------------------------|
| r   | refetch this issue from JIRA                  |
| c   | add a comment (ctrl+s in the modal to submit) |
| l   | link this issue to another key                |
| x   | remove the highlighted link (Links tab only)  |
| f   | edit the feature-flags custom field           |
| t   | edit local tags on this issue                 |
| A   | toggle the alert marker on this issue         |
| s   | focus the Surfaces panel                      |
| ↵   | (on a surface card) open the link modal       |
| esc | back                                          |

**Command palette** — `ctrl+p` opens Textual's palette. It includes:

- `Sync project…` — prompts for a project key.
- `Sync project KEY` — one entry per project already synced.

## Tags and alerts

Two local layers on top of the cache. Neither is pushed to JIRA.

- **Tags** are free-form labels on cached issues (`logo`, `branding`, `deal-placement`, ...). Use them however you like — categorise by area, by team, by intent.
- **Alerts** mark an issue as one you want *reminded of*. When you open a different cached issue, tendril compares its tags against every alert. Alerts that share ≥1 tag surface as cards in the right-hand panel of the Issue Detail screen; press `↵` on a card to link the two issues from a small modal.

The trigger *is* the tag overlap — there are no rule files to write. Marking an issue as an alert without tagging it does nothing (the CLI warns you).

```sh
# Tagging (idempotent; `set` replaces the whole set; empty `set` clears)
uv run tendril tag add MMINT-100 logo branding
uv run tendril tag set MMINT-200 logo deal-placement
uv run tendril tag list                 # all tagged issues
uv run tendril tag list MMINT-100       # one issue
uv run tendril tag list --json          # machine-readable, for LLM pipelines

# Alerts
uv run tendril alert add MMINT-100      # coworker's logo-alternatives issue
uv run tendril alert list
uv run tendril alert remove MMINT-100
```

In the TUI you can do all of this on the currently-open issue: `t` opens the tag editor, `A` toggles the alert marker.

The `tag list --json` shape (`{key: [tags...]}`) is deliberate: hand a batch of cached issues to Claude or a local model, get back tag assignments, feed them back through `tag set KEY tag1 tag2 …` in a loop.

## Feature flags

The `f` binding is only useful once you tell tendril the custom-field id for feature flags. Find it, then add it to `~/.config/tendril/config.toml`:

```toml
[fields]
feature_flags = "customfield_10457"
```

The field is assumed to be a JIRA labels-type custom field (payload shape `["flag_a", "flag_b"]`). Empty submit clears all flags.

## Design notes

- **Sync fills the cache; the watchlist, tags, and alerts sit on top.** Separate tables, each opt-in.
- **Every write refetches the touched issue.** No local mutation bypasses JIRA — the cache stays honest. Tags and alerts are local-only and never touch JIRA.
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
  alerts/           local-only tags + alerts; matcher for the Surfaces panel
  tui/              Textual app, screens, modals, command-palette provider
```
