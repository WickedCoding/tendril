# Contributing

Notes for hacking on tendril itself. If you just want to use it, `README.md` is the file you want.

## Setup

```sh
git clone git@github.com:WickedCoding/tendril.git
cd tendril
uv sync                             # creates .venv, installs runtime + dev deps
uv run tendril --help               # verify the source checkout runs
```

`uv sync` installs the `dev` dependency group (`pytest`, `pytest-asyncio`) alongside the runtime deps.

## Testing

```sh
uv run pytest
```

Unit + Textual `Pilot` smoke tests. `Pilot` runs under `asyncio_mode = "auto"` (configured in `pyproject.toml`), so async tests need no decorator.

Live integration tests hit the real configured JIRA and are gated on env vars — default to read-only:

```sh
TENDRIL_LIVE=1 TENDRIL_LIVE_ISSUE=SANDBOX-1 uv run pytest tests/integration
```

Run a single test:

```sh
uv run pytest tests/test_sync_pipeline.py::test_name
```

## Layout

```
src/tendril/
  cli.py            typer app; console_script `tendril`
  config.py         XDG paths, TOML load/save, keyring
  db/               SQLAlchemy 2 models, engine, schema init
  jira/             thin atlassian-python-api wrapper + DTOs
  sync/             fetch → normalize → upsert; sync_issue, sync_project, incremental
  operations/       single write layer (JIRA write → refetch)
  alerts/           local-only tags + alerts; matcher for the Surfaces panel
  tui/              Textual app, screens, modals, command-palette provider
```

Dependency direction is one-way: `cli.py` / `tui/` → `operations/` and `sync/` → `jira/` + `db/`. See `CLAUDE.md` for the fuller architecture notes and invariants worth respecting.

## Release

The distribution name on PyPI is `tendril-jira`; the import module and CLI command are both `tendril`. See `pyproject.toml` for the `[tool.uv.build-backend] module-name` override that keeps that split working.

```sh
# bump [project].version in pyproject.toml, commit
git tag -a vX.Y.Z -m "tendril-jira X.Y.Z"
git push && git push --tags

rm -f dist/tendril_jira-*
uv build
uv publish --token "$(uvx keyring get tendril-jira pypi-token)"
```

PyPI versions are unrepealable — a bad upload means bumping to X.Y.Z+1, never re-uploading the same version.
</content>
</invoke>