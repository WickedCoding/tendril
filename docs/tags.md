# tendril tag commands

Tags are a local layer on top of the cache: free-form labels on cached issues (`logo`, `branding`, `deal-placement`, …). They are never pushed to JIRA.

Tags drive the **Surfaces** panel on the Issue Detail screen. When you open a cached issue, every *other* cached issue that shares at least one tag surfaces as a card on the right. Press `↵` on a card to link the two issues. No opt-in marker — any shared tag surfaces by default.

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

## TUI shortcuts

On the Issue Detail screen:

- `t` opens the tag editor for the current issue.
- `s` moves focus to the Surfaces panel. Pressing `↵` on a surface card opens a small modal to link the current issue to the surfaced one.
