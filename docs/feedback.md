# Feedback

Open the command palette (`ctrl+p`) and pick **Send feedback…**. This is the only way in: there is no key binding and no CLI command.

Tendril shows a preview of the context it will add. Press `b` for a bug report or `i` for an idea. Tendril then opens a prefilled "new issue" page on [github.com/WickedCoding/tendril](https://github.com/WickedCoding/tendril) in your browser. Nothing is sent until you submit that page yourself, under your own GitHub account.

The repository is public. Do not type issue keys, names, customer data or JIRA URLs into the title or description.

## What Tendril adds

Tendril adds only the fields below. The set is fixed in `FeedbackContext` (`src/tendril/feedback.py`) and pinned by `tests/test_feedback.py`.

| Field | Example | Notes |
|---|---|---|
| tendril, python, os | `1.7.1`, `3.12.11`, `Darwin 27.2.0` | |
| terminal | `120x40` | Columns × rows |
| screens | `WatchlistScreen > IssueDetailScreen` | Screen class names only |
| focused | `DataTable` | Widget class name only, no id |
| recent actions | `IssueDetailScreen.add_comment` | Last 10 action names. Action parameters (such as issue keys) are dropped |
| config | `fields.sprint: yes` | Whether optional settings are set. Never field ids, names or counts |
| last error | `requests.exceptions.HTTPError` plus frames such as `tendril/operations/ops.py:42 in add_comment` | Type and code locations of the last failed background job. Never the message. Paths outside tendril, installed packages and the standard library show as `<external>` |

## What Tendril never adds

- Anything from the cache: issue keys, summaries, descriptions, comments, people, sprint or board names, statuses
- Your JIRA URL, email or account id
- Exception messages
- Absolute file paths, including your home directory

## Example

```
tendril: 1.7.1
python: 3.12.11
os: Darwin 27.2.0
terminal: 80x24
screens: WatchlistScreen > SprintWatchlistScreen
focused: DataTable
recent actions:
  - TendrilApp.open_sprint_watchlist
  - SprintWatchlistScreen.toggle_mine_filter
config:
  fields.feature_flags: no
  fields.sprint: no
  fields.story_points: no
  fields.skills: no
  skills.totals customised: no
  rollover.statuses customised: no
  boards: no
last error: json.decoder.JSONDecodeError
  <external>:17 in main
  <stdlib>/json/__init__.py:346 in loads
  <stdlib>/json/decoder.py:338 in decode
```

## Limits

- A crash that closes the TUI cannot be reported this way, because the palette is gone. Restart Tendril and describe the crash in the issue yourself.
- The `feedback` label comes from the issue template. The template is used only after this file is on the default branch.
