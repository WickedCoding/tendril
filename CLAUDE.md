# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Tendril is a personal, keyboard-driven JIRA companion: a local SQLite cache mirrors whole JIRA projects, a Textual TUI browses them offline, and a narrow write layer (comment / link / feature-flags) pushes back to JIRA. Scope is deliberately personal — it is not a team dashboard.

Python 3.12+, managed with `uv`. Entry point is the `tendril` console script (`tendril.cli:app`).

## Common commands

```sh
uv sync                                     # install deps into .venv
uv run tendril                              # launch the TUI (default when no subcommand)
uv run tendril config init                  # first-time setup (URL, email, API token)
uv run tendril whoami                       # verify auth against JIRA
uv run tendril sync project MMINT           # full project pull (paginated)
uv run tendril sync incremental             # refresh only issues changed since last sync
uv run tendril sync issue MMINT-42          # single-issue fallback (follows JIRA renames)
uv run tendril show MMINT-42                # print cached issue
uv run tendril watchlist add MMINT-42       # marker only; never touches JIRA
uv run pytest                               # unit + Textual Pilot smoke tests
uv run pytest tests/test_sync_pipeline.py::test_name  # single test
TENDRIL_LIVE=1 TENDRIL_LIVE_ISSUE=SANDBOX-1 uv run pytest tests/integration  # live tests
```

Config lives at `~/.config/tendril/config.toml` (XDG-respecting). The API token is stored via `keyring` under service `tendril`, keyed by email. The SQLite cache is at `~/.local/share/tendril/tendril.db`. Tests use the `isolated_xdg` fixture to redirect both dirs to `tmp_path`.

## Architecture

Layered, one direction of dependency: `cli.py` / `tui/` → `operations/` and `sync/` → `jira/` + `db/`.

- **`config.py`** — dataclass config + XDG paths + keyring wrapper. Raises `ConfigError` for missing files or locked keychain.
- **`jira/`** — `client.build()` returns an `atlassian.Jira`; `fetch.py` (reads) and `write.py` (writes) speak through `Protocol`s (`JiraLike`, `JiraWriteLike`) so tests can inject `FakeJira`. `dto.py` normalizes raw JIRA payloads into `IssueDTO`. `fetch.search_by_jql` paginates with JIRA Cloud's token-based `enhanced_jql` (`nextPageToken` + `isLast`), not the deprecated `startAt/total`.
- **`db/`** — SQLAlchemy 2 declarative models (`Issue`, `IssueLink`, `Comment`, `User`, `WatchlistEntry`, `ProjectSyncState`, `SyncState`). `engine.build_engine()` sets SQLite WAL + `synchronous=NORMAL` so the background sync worker doesn't block the UI thread. `schema.init_schema()` runs `create_all` and checks a `schema_version` row — there is **no Alembic yet**; a bumped `SCHEMA_VERSION` will raise until migrations land.
- **`sync/pipeline.py`** — `upsert_issue()` writes the Issue + related User rows + comments, and **replaces links wholesale** (JIRA doesn't tell us about deleted links, so diffing is unsafe).
- **`sync/commands.py`** — the higher-level ops: `sync_issue`, `sync_project`, `incremental_sync`, plus watchlist add/remove/list. Incremental sync only touches projects that have a `ProjectSyncState` row (i.e. `sync project` has run for them at least once) and uses a 5-minute safety buffer on the `updated >=` clause.
- **`operations/ops.py`** — the single write layer. Every write is `jira write → sync_issue(refetch)`. **No local mutation bypasses JIRA**; the cache stays honest by re-reading after every push.
- **`tui/`** — Textual `App`, screens (`watchlist`, `issue_detail`), modals (comment / link / flags / add / project). All JIRA I/O in the TUI goes through `TendrilApp.run_worker(..., thread=True)` and marshals results back with `call_from_thread`. The Jira client is built lazily so the empty-cache first run doesn't hit the keyring.

## Invariants worth respecting

- **Sync fills the cache; the watchlist is a marker on top.** Adding a watchlist key never fetches — if the key isn't cached, the CLI/TUI tells the user to `sync issue KEY`.
- **Whole-project sync is the intended path.** `sync issue KEY` exists as a fallback and to handle single-issue refresh after writes.
- **JIRA rename resilience** lives in `sync_issue`: when `dto.key != requested_key`, the watchlist entry migrates from old to new key before the upsert.
- **Links get replaced, not diffed** (see `_replace_links`). Comments are upserted by JIRA comment id.
- **Every write refetches** the touched issue via `sync_issue`. Preserve this when adding new operations.
- **Feature flags** are configured per-instance: `[fields].feature_flags = "customfield_XXXXX"` in `config.toml`. Assumed schema is a labels-type custom field (plain `list[str]` payload). The `f` binding is a no-op without this config.

## Testing notes

- `tests/conftest.py` provides `FakeJira` (fixture-backed, speaks the `enhanced_jql` token-pagination contract and a tiny JQL subset: `key in (...)`, `project = "X"`, `updated >= "..."` captured-but-ignored) plus `isolated_xdg` and a fresh SQLite `session` per test.
- Textual smoke tests use `Pilot` (async — `asyncio_mode = "auto"` in `pyproject.toml`).
- Live tests in `tests/integration/` are gated on `TENDRIL_LIVE=1` and hit the real configured JIRA. Default to read-only.
