# tendril database

The cache is a single SQLite file at `~/.local/share/tendril/tendril.db` (WAL mode, `synchronous=NORMAL` — set by `db/engine.build_engine()` so the sync worker doesn't block the UI).

Schema lives in `src/tendril/db/models.py` (SQLAlchemy 2 declarative). Changes go through Alembic revisions under `src/tendril/migrations/versions/`; `db.schema.init_schema()` runs `alembic upgrade head` on every startup.

Table names are **singular** (`issue`, not `issues`). Column names come straight from the models — no naming convention transforms them. A handful trip newcomers up:

- `issue.issuetype` — one word, not `issue_type`
- `issue.parent_key` — populated for both Sub-tasks and Story→Epic; JIRA Cloud unified both under `fields.parent`
- `issue.raw_json` — the untouched fetch payload, kept so we can re-derive fields without a resync

## Tables

### `issue`

One row per cached JIRA issue. Upserted by key on every fetch.

| column                  | type      | notes                                                     |
|-------------------------|-----------|-----------------------------------------------------------|
| `key`                   | TEXT PK   | JIRA key, e.g. `MMINT-888`                                |
| `summary`               | TEXT      |                                                           |
| `status`                | TEXT      | Status name string, not an id                             |
| `issuetype`             | TEXT      | e.g. `Story`, `Sub-task`, `Epic`, `Bug`                   |
| `assignee_account_id`   | TEXT      | FK-shaped ref to `user.account_id` (no enforced FK)       |
| `reporter_account_id`   | TEXT      | Same                                                      |
| `created`               | DATETIME  |                                                           |
| `updated`               | DATETIME  | Drives `sync incremental`                                 |
| `duedate`               | DATE      |                                                           |
| `parent_key`            | TEXT      | Parent issue key for Sub-tasks and Story→Epic             |
| `story_points`          | FLOAT     | Parsed from `[fields].story_points` custom field. NULL when the field is unset or unparseable. |
| `skills`                | JSON      | List of skill labels parsed from `[fields].skills` custom field (empty list by default). Handles both flat and option-object payloads. |
| `raw_json`              | JSON      | Original JIRA payload; source of truth for anything else  |
| `last_synced_at`        | DATETIME  | Set on every upsert                                       |

### `user`

Deduped author/assignee/reporter directory. Populated as issues and comments arrive.

| column          | type    | notes                                              |
|-----------------|---------|----------------------------------------------------|
| `account_id`    | TEXT PK | JIRA cloud account id                              |
| `display_name`  | TEXT    |                                                    |
| `email`         | TEXT    | May be null (JIRA privacy controls)                |

### `comment`

One row per JIRA comment. Upserted by JIRA's comment id.

| column               | type    | notes                                            |
|----------------------|---------|--------------------------------------------------|
| `id`                 | TEXT PK | JIRA comment id                                  |
| `issue_key`          | TEXT    | Parent issue                                     |
| `author_account_id`  | TEXT    |                                                  |
| `body`               | TEXT    | Flattened via `adf_to_text` — ADF loses fidelity |
| `created`            | DATETIME |                                                 |
| `updated`            | DATETIME |                                                 |

### `issue_link`

One row per JIRA issue-link, per direction. **Replaced wholesale on every issue upsert** — JIRA doesn't tell us about deleted links, so diffing is unsafe. See `sync.pipeline._replace_links`.

| column          | type      | notes                                                        |
|-----------------|-----------|--------------------------------------------------------------|
| `id`            | INT PK    | Autoincrement                                                |
| `source_key`    | TEXT      | The issue the link was fetched from                          |
| `target_key`    | TEXT      | The other end                                                |
| `link_type`     | TEXT      | e.g. `Blocks`, `Relates` (matches `link_type.name`)          |
| `direction`     | TEXT      | `outward` or `inward` relative to `source_key`               |
| `jira_link_id`  | TEXT      | JIRA's id for the link                                       |

Unique constraint: `(source_key, target_key, link_type, direction)`.

### `link_type`

The set of link types the JIRA instance offers. Populated by `tendril sync link-types`; consumed by the link modals so users pick from a real list instead of typing a string.

| column     | type    | notes                                                 |
|------------|---------|-------------------------------------------------------|
| `name`     | TEXT PK | What JIRA's create-link endpoint expects              |
| `outward`  | TEXT    | Human phrase, e.g. `blocks`                           |
| `inward`   | TEXT    | Human phrase, e.g. `is blocked by`                    |

### `sprint`

One row per JIRA sprint we've seen. Upserted by JIRA sprint id; state (`future` / `active` / `closed`) is refreshed on every upsert so the cache tracks the current phase.

| column           | type      | notes                             |
|------------------|-----------|-----------------------------------|
| `id`             | INT PK    | JIRA's global sprint id           |
| `name`           | TEXT      |                                   |
| `state`          | TEXT      | `future` \| `active` \| `closed`  |
| `board_id`       | INT       |                                   |
| `goal`           | TEXT      |                                   |
| `start_date`     | DATETIME  |                                   |
| `end_date`       | DATETIME  |                                   |
| `complete_date`  | DATETIME  |                                   |

### `issue_sprint`

Join table: which issues are in which sprints. **Replaced wholesale on every issue upsert** — same reason as `issue_link`.

| column       | type    | notes            |
|--------------|---------|------------------|
| `issue_key`  | TEXT PK | Composite with sprint_id |
| `sprint_id`  | INT PK  |                  |

Index: `ix_issue_sprint_sprint_id` on `sprint_id`.

### `watchlist_entry`

Local-only marker on top of the cache. Adding a key here **never** fetches — if the issue isn't cached, the CLI/TUI tells the user to `sync issue KEY`.

| column       | type      | notes                                    |
|--------------|-----------|------------------------------------------|
| `issue_key`  | TEXT PK   |                                          |
| `added_at`   | DATETIME  |                                          |
| `note`       | TEXT      |                                          |
| `position`   | INT       | Sort order in the watchlist screen       |

### `issue_tag`

Local free-form label on a cached issue. Never pushed to JIRA. Composite primary key `(issue_key, tag)`.

| column       | type    | notes  |
|--------------|---------|--------|
| `issue_key`  | TEXT PK |        |
| `tag`        | TEXT PK |        |

### `rollover_attempt`

In-flight or failed sprint-rollover state. One row per source sprint; deleted on success. A lingering row on re-entry to the rollover screen signals a partial rollover that the user can resume from `completed_step + 1`.

| column                | type      | notes                                                       |
|-----------------------|-----------|-------------------------------------------------------------|
| `source_sprint_id`    | INT PK    | JIRA sprint id of the sprint being rolled over              |
| `target_sprint_id`    | INT       | JIRA sprint id of the projected next sprint                 |
| `selected_issue_keys` | JSON      | Issue keys the user picked to carry over                    |
| `moved_issue_keys`    | JSON      | Keys the move step actually sent to JIRA (for resume)       |
| `completed_step`      | TEXT      | `move_issues` \| `close_source` \| `start_target` \| NULL   |
| `error`               | TEXT      | Last exception message; cleared when `start_rollover` refreshes the row |
| `created_at`          | DATETIME  |                                                             |
| `updated_at`          | DATETIME  | Bumped on every step commit                                 |

### `rollover_log`

Successful rollover history. Sprint names are denormalized so the log stays readable even if the sprint rows are later evicted from the cache.

| column                 | type      | notes                              |
|------------------------|-----------|------------------------------------|
| `id`                   | INT PK    | Autoincrement                      |
| `source_sprint_id`     | INT       |                                    |
| `source_sprint_name`   | TEXT      | Denormalized at commit time        |
| `target_sprint_id`     | INT       |                                    |
| `target_sprint_name`   | TEXT      | Denormalized at commit time        |
| `moved_issue_keys`     | JSON      | Keys actually moved                |
| `committed_at`         | DATETIME  |                                    |

### `project_sync_state`

Per-project bookkeeping. A row exists once `sync project KEY` has run at least once — that row is what makes `sync incremental` include the project.

| column                       | type      | notes                          |
|------------------------------|-----------|--------------------------------|
| `project_key`                | TEXT PK   | e.g. `MMINT`                   |
| `last_full_sync_at`          | DATETIME  |                                |
| `last_incremental_sync_at`   | DATETIME  |                                |

### `alembic_version`

Alembic's own bookkeeping. Don't touch it.

## Invariants worth respecting

Repeated from `CLAUDE.md`, because they are properties of the schema itself:

- **Links and sprint join rows are replaced, not diffed.** JIRA doesn't emit deletions.
- **Comments are upserted by JIRA comment id.** Sprint metadata rows are upserted by JIRA sprint id.
- **Every write refetches** the touched issue via `sync_issue`; the cache stays honest by re-reading after every push.
- **The watchlist is a marker on top of the cache** — it never triggers a fetch.
- **`rollover_attempt` is per-source-sprint state**, not a queue. Its presence signals a partial rollover; success deletes it and appends to `rollover_log`.

## Quick reference for ad-hoc queries

```sh
sqlite3 ~/.local/share/tendril/tendril.db

.tables
.schema issue
SELECT key, issuetype, parent_key, summary FROM issue WHERE key = 'MMINT-888';
SELECT key, issuetype, status FROM issue WHERE parent_key = 'MMINT-757';
SELECT s.name, s.state FROM sprint s JOIN issue_sprint j ON j.sprint_id = s.id WHERE j.issue_key = 'MMINT-888';
SELECT source_key, direction, link_type, target_key FROM issue_link WHERE source_key = 'MMINT-888';
```
