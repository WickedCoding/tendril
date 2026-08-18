# tendril sync commands

Sync pulls JIRA issues into the local SQLite cache. Everything else in tendril — the TUI, the watchlist, tags, alerts — reads from that cache. The intended workflow is `sync project KEY` once per project, then `sync incremental` from there.

## `tendril sync project KEY`

Pulls every issue in a JIRA project into the cache, paginated over JIRA Cloud's token-based search.

```sh
uv run tendril sync project MMINT
```

Run this once per project you care about. The command records a `ProjectSyncState` row so `sync incremental` knows to include this project on future runs.

Safe to re-run — issues are upserted by key.

## `tendril sync incremental`

Refetches issues updated since the last sync, across every project you've run `sync project` on. This is the cheap keep-fresh path.

```sh
uv run tendril sync incremental
```

If you've never run `sync project`, the command tells you and exits. It applies a 5-minute safety buffer to the "updated since" clause so nothing falls through the cracks between runs.

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

Use it after `config init` or after rotating the API token, to confirm tendril can reach JIRA before you kick off a large project sync.
