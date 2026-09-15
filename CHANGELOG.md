# Changelog

All notable changes to Tendril will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-09-15

### Added
- Sprint rollover (`Shift+R` in the TUI): pick an active source sprint, review a two-panel view of source vs. projected next sprint, tune the carry-over selection and per-issue SP reductions, preview the full projected roster, and commit. On confirm, four ordered JIRA writes run — move issues → close source → start target → log — with per-step state persisted to a `rollover_attempt` row so failures can be resumed via `Shift+R` from the last successful step. Success appends a local `rollover_log` entry and a transient toast.
- Story Points and skill labels are now first-class columns on the `issue` row (`[fields].story_points` and `[fields].skills` in `config.toml`), backfilled on next sync.
- New config surfaces to drive the rollover screen: `[rollover].statuses` (preselected carry-over statuses), `[skills].totals` (per-skill roll-ups), and `[boards.<PROJECT>].sprint_pattern` (regex with named groups `prefix` and `number` for predicting the next sprint's name).

## [1.3.0] - 2026-09-01

### Added
- Command palette (`Ctrl+P`) now offers per-column sort entries for the active table — watchlist, sprint watchlist, and issue-detail Links tab. Each column exposes ascending and descending entries; the choice survives reloads and syncs.

### Removed
- The `alert` marker and its CLI (`tendril alert add/remove/list`) are gone. The Surfaces panel now fires on any shared tag by default — every tagged issue is effectively an "alert." The `A` binding on the Issue Detail screen is retired, and the `issue_alert` table is dropped by migration `0002`.

## [1.2.3] - 2026-08-26

### Added
- `watchlist add` accepts `--tag/-t` (repeatable) to apply tags to each added key.
- `watchlist list` shows a `tags` column alongside the existing note column.

## [1.2.2] - 2026-08-19

### Added
- `sync project` and `sync issue` now accept multiple keys in one invocation.
- Sprint watchlist shows the assignee column, matching the main watchlist.
- Surface-card modal shows a shortened description alongside the title.

### Changed
- Watchlist add/remove is cursor-driven and now works from the sprint watchlist too — no need to switch views to (un)watch an issue you're looking at.

## [1.2.1] - 2026-08-18

### Added
- TUI theme selection is persisted across sessions.
- PyPI publishing runs from GitHub Actions via a trusted publisher (OIDC), so releases no longer need a local API token.

### Changed
- Watchlist polish: footer key order, add-modal prefill from the current cursor, and better modal sizing.

## [1.2.0] - 2026-08-18

### Added
- Sprint watchlist (`Shift+S`): every cached issue in an active sprint, no configuration beyond the `[fields].sprint` custom-field id.
- `m` filter across the watchlist, sprint watchlist, and Links tab — narrows to "assignee = me" using the account id stored by `tendril whoami`.

### Changed
- User columns render display names instead of raw JIRA account ids.
- Watchlist columns rebalanced so summaries no longer get squeezed on narrow terminals.
- Schema management moved to Alembic — `init_schema` runs `alembic upgrade head` on every startup, so new revisions apply on the next launch.

## [1.1.0] - 2026-08-18

### Added
- JIRA link types are cached locally, and their configured phrases ("blocks", "is blocked by", …) are used across the Links tab and the link-write path instead of raw type names.
- Global search matches on local tags; the `#tag` prefix narrows the search to tags only.

### Changed
- README points at the installed `tendril` command; contributor / development setup moved to `CONTRIBUTING.md`.

## [1.0.0] - 2026-08-18

First public release on PyPI as `tendril-jira`.

### Added
- Local SQLite cache mirroring whole JIRA projects, with token-paginated `enhanced_jql` search and incremental refresh via `sync incremental`.
- Watchlist as a local marker on top of the cache — `watchlist add/remove/list` never touches JIRA, and rename-resilient `sync issue` migrates keys when JIRA renames an issue.
- Textual TUI over the cache: watchlist screen, issue detail with Links tab (including child issues, parent navigation, and status column), and command palette entry for project sync.
- Narrow write layer: comment, link, and feature-flags modals. Every write refetches the touched issue via `sync_issue` so the cache stays honest.
- Global `/` search modal that jumps to any cached issue by key or summary.
- "All issues" overview with watchlist and open-only filters.
- Local tags and alerts on issues, exposed via a Surfaces panel in issue detail.
- JIRA descriptions rendered with basic styling instead of a flat text dump; project sync caches descriptions so the styled render works offline.
- Keyring-backed API token storage (service `tendril`, keyed by email), XDG-respecting config at `~/.config/tendril/config.toml`, and a live-integration test scaffold gated on `TENDRIL_LIVE=1`.
- CLI reference split into `docs/` per command group; README trimmed to short pitches with links.
- SPDX metadata and project URLs; distribution renamed to `tendril-jira` (import name remains `tendril`).
