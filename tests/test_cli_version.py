from __future__ import annotations

from importlib.metadata import version

from typer.testing import CliRunner

from tendril.cli import app


def test_version_flag_prints_installed_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"tendril {version('tendril-jira')}"
