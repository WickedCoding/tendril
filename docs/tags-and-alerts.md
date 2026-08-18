# tendril tag and alert commands

Tags and alerts are two local layers on top of the cache. Neither is pushed to JIRA.

- **Tags** are free-form labels on cached issues (`logo`, `branding`, `deal-placement`, …). Use them however you want — categorise by area, by team, by intent.
- **Alerts** mark an issue as one you want reminded of. When you open a different cached issue in the TUI, alerts that share at least one tag surface as cards on the right-hand Surfaces panel of the Issue Detail screen. Press `↵` on a card to link the two issues.

The trigger is *tag overlap*. There are no rule files. Marking an issue as an alert without tagging it does nothing, and the CLI warns you when that happens.

## Tag commands

### `tendril tag add KEY TAGS...`

Adds one or more tags to an issue. Idempotent.

```sh
uv run tendril tag add MMINT-100 logo branding
```

### `tendril tag remove KEY TAGS...`

Removes named tags from an issue. Other tags on the issue stay.

```sh
uv run tendril tag remove MMINT-100 branding
```

### `tendril tag set KEY TAGS...`

Replaces the whole tag set for an issue. Pass no tags to clear.

```sh
uv run tendril tag set MMINT-200 logo deal-placement
uv run tendril tag set MMINT-200                       # clears every tag
```

Use this for bulk overwrites — for example, when feeding a language model's output back in.

### `tendril tag list [KEY] [--json]`

Lists tagged issues. Without a key, lists every tagged issue. With a key, lists only that issue's tags.

```sh
uv run tendril tag list
uv run tendril tag list MMINT-100
uv run tendril tag list --json                         # machine-readable
uv run tendril tag list MMINT-100 --json
```

The `--json` shape is `{key: [tags, ...]}`. Convenient for handing a batch of cached issues to a language model and looping its output back through `tag set KEY tag1 tag2 …`.

## Alert commands

### `tendril alert add KEY`

Marks an issue as an alert. If the issue has no tags, the command warns you — the alert won't fire against any other issue until you tag it.

```sh
uv run tendril alert add MMINT-100
```

### `tendril alert remove KEY`

Removes the alert marker. Tags on the issue are left alone.

```sh
uv run tendril alert remove MMINT-100
```

### `tendril alert list`

Prints every alert with its tags and the timestamp it was marked.

```sh
uv run tendril alert list
```

An alert whose issue has no tags appears with `— (won't fire)` in the tags column — a reminder to add tags or drop the marker.

## TUI shortcuts

On the Issue Detail screen:

- `t` opens the tag editor for the current issue.
- `A` toggles the alert marker on the current issue.
- `s` moves focus to the Surfaces panel. Pressing `↵` on a surface card opens a small modal to link the current issue to the alert.
