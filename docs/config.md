# tendril config commands

`tendril config` manages the local config file and API token. Config lives at `~/.config/tendril/config.toml`. The API token lives in your OS keyring under service `tendril`, keyed by the email you set — it is never written to disk in plain text.

## `tendril config init`

Interactive first-run setup. Prompts for JIRA URL, your Atlassian email, and an API token, then writes the config file and stores the token in the keyring.

```sh
uv run tendril config init
```

Create the API token at [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens). Verify the setup immediately with:

```sh
uv run tendril whoami
```

## `tendril config show`

Prints the current config. The API token is never printed.

```sh
uv run tendril config show
```

Output covers the config file path, data directory, JIRA URL and email, configured custom-field ids, the default link type, per-skill totals and rollover statuses, and any per-project board sections.

## Editing the config directly

Some settings aren't covered by `config init`. Edit `~/.config/tendril/config.toml` by hand:

```toml
[jira]
url = "https://acme.atlassian.net"
email = "you@example.com"

[fields]
feature_flags = "customfield_10457"    # enables the `f` binding in the TUI
sprint = "customfield_10020"           # enables the sprint watchlist (Shift+S in the TUI)
story_points = "customfield_10032"     # required for the sprint rollover screen (Shift+R)
skills = "customfield_10134"           # optional — a multi-select for per-skill totals

[links]
default_link_type = "Relates"          # default JIRA link type for `l`

[overview]
done_statuses = [                      # rows the TUI overview `o` filter hides
  "Ready for Acc",
  "Ready for Prod",
  "Closed",
  "Deployed to Acc",
  "Deployed to Prod",
]

[rollover]
statuses = [                           # source-sprint statuses preselected for carry-over
  "To Do",
  "In Progress",
  "Code Review",
  "Functional Review",
]

[skills]
totals = ["Backend", "Frontend"]       # which skill labels get rolled-up totals in the rollover screen

[boards.MMINT]                         # optional per-project section
sprint_pattern = '^(?P<prefix>.*?)(?P<number>\d+)$'  # regex with named groups `prefix` and `number`
```

Change `done_statuses` to match your project's workflow — anything not in this list counts as "open" for the filter.

The sprint rollover screen (`Shift+R`) leans on `[fields].story_points`, `[rollover].statuses`, `[skills].totals`, and `[boards.<PROJECT>].sprint_pattern`. See [rollover.md](rollover.md) for how each field shapes the projected next-sprint totals and the resume-on-failure path.

## Where the files live

- Config file: `~/.config/tendril/config.toml` (respects `XDG_CONFIG_HOME`)
- Cache database: `~/.local/share/tendril/tendril.db` (respects `XDG_DATA_HOME`)
- API token: OS keyring, service `tendril`, key `<your email>`
- Version check: `~/.config/tendril/version-check.toml` (respects `XDG_CONFIG_HOME`)

## Update check

Once a day, tendril asks pypi.org for the latest `tendril-jira` release (2-second timeout) and records the result in `version-check.toml`:

```toml
checked_at = "2026-10-22T09:14:03+00:00"
current = "1.6.0"
latest = "1.7.0"
```

Within a day of `checked_at`, tendril reads `latest` from the file and makes no network call. A failed request still updates `checked_at`, so an offline machine retries the next day, not on every command.

When `latest` is newer than the installed version:

- `tendril` (the TUI) opens an "Update available" popup on launch. Enter or Esc closes it.
- Every other command prints a yellow notice as its first line. Commands run with `--json` never print it, so their output stays parseable.

Set `TENDRIL_NO_VERSION_CHECK=1` to turn the check off.
