# tendril sync and project commands

Sync pulls JIRA issues into the local SQLite cache. Everything else in tendril — the TUI, the watchlist, tags — reads from that cache. The intended workflow is `project sync KEY` once per project, then a bare `tendril sync` from there.

Project-scoped operations live under `tendril project …`; the remaining sync verbs (the top-level incremental refresh, per-issue fallback, link-type refresh) live under `tendril sync …`.

## `tendril project sync KEY [KEY ...]`

Pulls every issue in one or more JIRA projects into the cache, paginated over JIRA Cloud's token-based search.

```sh
uv run tendril project sync MMINT
```

Run this once per project you care about. The command records a `ProjectSyncState` row so `tendril sync` knows to include this project on future runs.

Safe to re-run — issues are upserted by key. Each project syncs independently; a failure on one logs the error and the batch continues, and the exit code is 2 if any project failed.

## `tendril project drop KEY [KEY ...]`

Purges every cached row belonging to the named projects. Runs with no confirmation.

```sh
uv run tendril project drop MMINT
```

Removes issues, comments, links (on either side), sprint join rows, and the `ProjectSyncState` marker. Preserves user data and cross-project state: watchlist entries (they'll show as "not synced" until you re-sync), local tags (they re-attach on next sync), shared sprint metadata, and rollover history.

## `tendril sync`

Refetches issues updated since the last sync, across every project you've run `project sync` on. This is the cheap keep-fresh path and the top-level face of the sync group — invoked bare, with no subcommand.

```sh
uv run tendril sync
```

If you've never run `project sync`, the command tells you and exits. It applies a 5-minute safety buffer to the "updated since" clause so nothing falls through the cracks between runs.

The TUI also fires this on startup when there's at least one synced project.

## `tendril sync issue KEY`

Fallback for a single issue. Useful when you know a specific issue has changed and you want it now, or when JIRA has moved an issue to another project.

```sh
uv run tendril sync issue MMINT-42
```

If JIRA returns the issue under a different key (a project rename), the cache upserts under the new key and any watchlist entry for the old key migrates over. The command prints a note when that happens:

```
Note: MMINT-42 has been moved to CORE-42. Watchlist entry migrated.
```

## `tendril show KEY`

Prints an issue's cached fields. Read-only — never touches JIRA.

```sh
uv run tendril show MMINT-42
```

Exits with an error if the key isn't in the cache — sync it first.

## `tendril whoami`

Verifies auth by fetching your own JIRA profile.

```sh
uv run tendril whoami
```

Use it after `config init` or after rotating the API token, to confirm tendril can reach JIRA before you kick off a large project sync. `whoami` also persists your `accountId` into `~/.config/tendril/config.toml`.
