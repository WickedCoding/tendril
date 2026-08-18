# tendril watchlist commands

The watchlist is a marker layer on top of the cache. Adding a key never fetches from JIRA — it flags a cached issue so the TUI's overview highlights it in the accent color and so `watchlist list` can print it as a short curated set.

If a key isn't in the cache when you add it, the CLI tells you and points at `sync project` or `sync issue` to populate it.

## `tendril watchlist add KEYS...`

Adds one or more issue keys. Idempotent — adding a key that's already on the watchlist is a no-op.

```sh
uv run tendril watchlist add MMINT-42
uv run tendril watchlist add MMINT-42 MMINT-100 MMINT-150
uv run tendril watchlist add MMINT-42 --note "waiting on QA"
```

Uncached keys are reported after the add:

```
Watchlist size: 3 entries after add.
Not yet in cache: MMINT-999
Run `tendril sync project KEY` or `tendril sync issue KEY` to populate.
```

## `tendril watchlist remove KEYS...`

Removes one or more keys from the watchlist. The cached issue rows are left alone — only the marker goes.

```sh
uv run tendril watchlist remove MMINT-42
uv run tendril watchlist remove MMINT-42 MMINT-100
```

Removing a key that isn't on the watchlist is silent.

## `tendril watchlist list`

Prints the current watchlist with the cached issue's status, summary, updated timestamp, and any note.

```sh
uv run tendril watchlist list
```

Entries whose issue isn't cached yet appear with `-not synced-` in the status column.

## TUI shortcuts

The overview screen (the default when you launch `tendril`) shows every cached issue with a `★` marker on watchlisted rows:

- `a` opens a modal to add a key to the watchlist.
- `d` removes the highlighted row from the watchlist (the cached row stays).
- `w` toggles the "watchlist only" filter.
