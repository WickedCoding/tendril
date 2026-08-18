# tendril

A keyboard-driven JIRA companion. A local SQLite cache mirrors whole JIRA projects; a Textual TUI browses them offline; a small set of write operations (comment, link, feature-flags) lets you push back without leaving the terminal. Local **tags** and **alerts** surface related issues as you browse — the coworker's "logos need light/dark alternatives" issue pops up as a card when you open the PO's "add logo to layout" ticket, ready to link in one keystroke.

Deliberately narrow: this is a personal tool, not a team dashboard.

## Install

```sh
uv tool install tendril-jira        # or: pipx install tendril-jira
tendril config init                 # walks through URL, email, API token
tendril whoami                      # verifies auth
```

Both installers put `tendril` on your `PATH`. Config lives at `~/.config/tendril/config.toml`; the API token in the OS keyring; the cache at `~/.local/share/tendril/tendril.db`. See [docs/config.md](docs/config.md) for token rotation, manual TOML editing, and per-instance settings.

For a throwaway trial without installing, `uvx tendril-jira config init` works too — but the config, keyring entry, and cache still persist on disk between runs.

## First sync

```sh
tendril sync project MMINT   # pulls every issue in MMINT into the cache (paginated)
tendril show MMINT-42        # prints an issue from the cache
tendril sync incremental     # from then on, refreshes only what changed
```

See [docs/sync.md](docs/sync.md) for `sync issue` (single-issue fallback), the rename-migration behavior, and the intended workflow in detail.

## Watchlist

A marker layer on top of the cache — adding a key never touches JIRA. Watchlisted rows show a `★` marker in the TUI overview and render in the accent color.

See [docs/watchlist.md](docs/watchlist.md) for `watchlist add`, `remove`, `list`, and the TUI shortcuts.

## TUI

Run with no subcommand:

```sh
tendril
```

Two screens plus a global search.

**Overview** — a table of every cached issue, with a `★` column marking watchlisted rows.

| key | binding                                      |
|-----|----------------------------------------------|
| a   | add issue key to watchlist                   |
| d   | drop watchlist marker on highlighted row     |
| w   | toggle watchlist-only filter                 |
| o   | toggle open-only filter (hides done statuses)|
| s   | run incremental sync                         |
| r   | reload from cache                            |
| ↵   | open issue detail                            |
| q   | quit                                         |

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
| p   | open this issue's parent                      |
| ↵   | (on a surface card) open the link modal       |
| esc | back                                          |

**Global** — works from any screen:

| key    | binding                                                |
|--------|--------------------------------------------------------|
| /      | search cached issues by key, tag, or summary (`#tag` narrows to tags only) |
| ctrl+p | command palette (`Sync project…` + one per synced project) |

## Tags and alerts

Two local layers on top of the cache. Neither is pushed to JIRA.

- **Tags** are free-form labels on cached issues (`logo`, `branding`, `deal-placement`, …).
- **Alerts** mark an issue as one you want reminded of. When you open a different cached issue, alerts that share at least one tag surface as cards on the right-hand Surfaces panel. Press `↵` on a card to link the two issues.

The trigger is tag overlap — there are no rule files.

See [docs/tags-and-alerts.md](docs/tags-and-alerts.md) for the full CLI (`tag add/remove/set/list`, `alert add/remove/list`), the `--json` output shape for LLM pipelines, and the TUI shortcuts.

## Feature flags

The `f` binding in the TUI is only useful once you set the custom-field id for feature flags:

```toml
[fields]
feature_flags = "customfield_10457"
```

The field is assumed to be a JIRA labels-type custom field (payload shape `["flag_a", "flag_b"]`). Empty submit clears all flags. Full config layout: [docs/config.md](docs/config.md).

## Design notes

- **Sync fills the cache; the watchlist, tags, and alerts sit on top.** Separate tables, each opt-in.
- **Every write refetches the touched issue.** No local mutation bypasses JIRA — the cache stays honest. Tags and alerts are local-only and never touch JIRA.
- **Whole-project sync only.** Per-issue single fetches exist (`sync issue KEY`) but are a fallback; the intended workflow is `sync project KEY` once, then `sync incremental` from there.
- **JIRA rename resilience.** If JIRA has moved an issue to another project, `sync issue OLDKEY` follows the redirect, cache is upserted under the new key, and any watchlist entry for the old key is migrated.
- **No Alembic yet.** `Base.metadata.create_all()` plus a `schema_version` row carries us here. Alembic joins when the first breaking schema change lands.

## Contributing

Setup, tests, layout, and the release rite live in [CONTRIBUTING.md](CONTRIBUTING.md).
