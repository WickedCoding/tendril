# tendril sprint rollover

The sprint rollover screen moves selected issues from an active sprint into the next sprint, then closes the source and starts the target. It runs from the TUI — there is no CLI equivalent.

## Prerequisites

Add the following to `~/.config/tendril/config.toml`. Every field is opt-in; the screen refuses to open cleanly without the ones marked required.

```toml
[fields]
sprint = "customfield_10020"         # required — same field the sprint watchlist uses
story_points = "customfield_10032"   # required — Story Points custom field
skills = "customfield_10134"         # optional — multi-select for per-skill totals

[rollover]
statuses = ["To Do", "In Progress", "Code Review", "Functional Review"]

[skills]
totals = ["Backend", "Frontend"]     # which skill labels get rolled-up totals

[boards.MMINT]
sprint_pattern = '^(?P<prefix>.*?)(?P<number>\d+)$'
```

- **`[rollover].statuses`** are the statuses tendril preselects for carry-over. Others can still be selected by hand.
- **`[skills].totals`** drives the per-skill totals in the projected next-sprint panel. Skills are counted **duplicate-per-skill**: an issue with `["Backend", "Frontend"]` contributes its full SP to both totals.
- **`sprint_pattern`** predicts the next sprint's name by incrementing `number` while preserving zero-padding (`Sprint 09` → `Sprint 10`, `S001` → `S002`). The pattern is a regex with named groups `prefix` and `number`. Falls back to the default `^(?P<prefix>.*?)(?P<number>\d+)$` when a project has no `[boards.<PROJECT>]` section.

Skills is a JIRA multi-select. Both flat `["Backend"]` and option-object `[{"value": "Backend"}]` payloads are handled — no schema tweaks needed on your JIRA side.

## Workflow

1. Launch the TUI (`uv run tendril`) and press `Shift+R` from any screen. A picker lists every cached **active** sprint.
2. Pick a source sprint. The two-panel view opens with:
   - **Left panel** — source-sprint issues, sorted so rollover statuses cluster at the top. Issues in rollover statuses are preselected (marked `✓`).
   - **Right panel** — projected next sprint. Carry-overs from the source (marked `→`) appear above the existing target issues (dim). Read-only: cursor and focus are disabled — existing target rows are immovable from tendril's side.
3. Above the panels, a totals strip shows Story Points:
   - **Active** line: source totals — `total | to-do+in-progress | BE: N | FE: N`.
   - **Future** line: projected target totals as `{base}+{delta}SP` per bucket. Base is the existing target roster; delta is the carry-over contribution (after reductions).
4. Adjust selection and reductions:
   - `space` — toggle the cursor row's selection
   - `a` — reselect all rollover-status issues
   - `n` — clear selection
   - `e` — set a per-issue SP reduction (local-only; never writes to JIRA). The projected carry-over SP drops by the reduction; the moved issue itself arrives in JIRA with SP unchanged.
   - `r` — reload from cache
5. Press `c` for the preview modal. It shows the full projected roster (carry-overs + existing target issues) and the projected totals. `enter` / `y` confirms; `esc` / `q` cancels.
6. On confirm, the rollover runs four ordered steps against JIRA:
   1. Move selected issues into the target sprint
   2. Close the source sprint
   3. Start the target sprint
   4. Log the success (local `rollover_log` row + a transient toast in the TUI)

## Failure recovery

If any step fails, the `rollover_attempt` row survives with the last successful step and the error text. Re-open the same source sprint and the status line reports:

```
⚠ partial rollover detected — last completed step: move_issues. Press `Shift+R` to resume
```

Press `Shift+R` to resume from the failed step. No rollback is attempted — JIRA writes are not fully reversible. Step 1 is idempotent, so re-sending keys already in the target is safe.

## What tendril does *not* do

- **Never creates sprints.** If the projected next sprint doesn't exist in JIRA (and therefore isn't cached), the target header shows `No cached sprint named 'Sprint 31' on this board.` and the preview refuses to open. Create the sprint in JIRA first, sync, then reload.
- **Never posts JIRA comments on moved issues.** The success log is local only.
- **Never rewrites the Story Points field on moved issues.** SP reductions are local bookkeeping used to shape the projected right-panel totals — they never propagate to JIRA.
- **Never removes existing target-sprint issues.** If you need to drop one from the next sprint, do it in JIRA first, then reload the rollover screen.

## Key bindings summary

| key       | binding                                                    |
|-----------|------------------------------------------------------------|
| `space`   | toggle selection on the source row                         |
| `a`       | select all source issues whose status is in `[rollover].statuses` |
| `n`       | clear selection                                            |
| `e`       | set / clear the SP reduction on the cursor row             |
| `c`       | open the preview modal                                     |
| `r`       | reload from cache                                          |
| `Shift+R` | resume a partial rollover                                  |
| `esc`/`q` | back to the previous screen                                |
