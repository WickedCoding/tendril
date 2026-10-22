from __future__ import annotations

import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import tomli_w
from typer.testing import CliRunner

from tendril import version_check
from tendril.cli import app

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def enabled(isolated_xdg: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(version_check.DISABLE_ENV, raising=False)
    monkeypatch.setattr(version_check, "installed_version", lambda: "1.6.0")
    return isolated_xdg


def _write(**state) -> None:
    path = version_check.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(state).encode())


def _read() -> dict:
    return tomllib.loads(version_check.state_path().read_text())


def _fail_fetch() -> str | None:
    raise AssertionError("fetch must not be called")


def test_fresh_state_skips_fetch(enabled) -> None:
    _write(checked_at=(NOW - timedelta(hours=23)).isoformat(), current="1.6.0", latest="1.7.0")
    assert version_check.check(now=NOW, fetch=_fail_fetch) == "1.7.0"


def test_stale_state_fetches_and_records(enabled) -> None:
    _write(checked_at=(NOW - timedelta(days=2)).isoformat(), current="1.5.0", latest="1.6.0")
    assert version_check.check(now=NOW, fetch=lambda: "1.8.0") == "1.8.0"
    assert _read() == {"checked_at": NOW.isoformat(), "current": "1.6.0", "latest": "1.8.0"}


def test_missing_state_fetches_and_creates_file(enabled) -> None:
    assert version_check.check(now=NOW, fetch=lambda: "1.6.0") is None
    assert _read()["latest"] == "1.6.0"


def test_failed_fetch_stamps_time_and_keeps_previous_latest(enabled) -> None:
    _write(checked_at=(NOW - timedelta(days=2)).isoformat(), current="1.6.0", latest="1.7.0")
    assert version_check.check(now=NOW, fetch=lambda: None) == "1.7.0"
    assert _read() == {"checked_at": NOW.isoformat(), "current": "1.6.0", "latest": "1.7.0"}
    # Stamped, so the next call within a day does not retry.
    assert version_check.check(now=NOW + timedelta(hours=1), fetch=_fail_fetch) == "1.7.0"


def test_failed_fetch_without_history_returns_none(enabled) -> None:
    assert version_check.check(now=NOW, fetch=lambda: None) is None
    assert "latest" not in _read()


@pytest.mark.parametrize("latest", ["1.6.0", "1.5.9", "not-a-version"])
def test_no_notice_when_not_newer(enabled, latest: str) -> None:
    assert version_check.check(now=NOW, fetch=lambda: latest) is None


def test_upgrade_clears_notice_without_refetch(enabled, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(checked_at=NOW.isoformat(), current="1.6.0", latest="1.7.0")
    monkeypatch.setattr(version_check, "installed_version", lambda: "1.7.0")
    assert version_check.check(now=NOW, fetch=_fail_fetch) is None


def test_corrupt_state_is_treated_as_missing(enabled) -> None:
    version_check.state_path().parent.mkdir(parents=True, exist_ok=True)
    version_check.state_path().write_text("this is = = not toml")
    assert version_check.check(now=NOW, fetch=lambda: "1.7.0") == "1.7.0"


def test_env_var_disables_check(enabled, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(version_check.DISABLE_ENV, "1")
    assert version_check.check(now=NOW, fetch=_fail_fetch) is None
    assert not version_check.state_path().exists()


# ---- CLI wiring ----


@pytest.fixture
def update_known(isolated_xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_check, "check", lambda: "9.9.9")
    monkeypatch.setattr(version_check, "installed_version", lambda: "1.6.0")


def test_cli_prints_notice_as_first_line(update_known) -> None:
    result = CliRunner().invoke(app, ["watchlist", "list"])
    assert result.exit_code == 0, result.output
    first = result.output.splitlines()[0]
    assert first == "tendril 9.9.9 is available (installed 1.6.0). Upgrade: uv tool upgrade tendril-jira"


def test_cli_json_output_has_no_notice(update_known) -> None:
    result = CliRunner().invoke(app, ["search", "--status=Nope", "--json"])
    assert result.exit_code == 0, result.output
    assert "9.9.9" not in result.output
    json.loads(result.output)


def test_cli_version_flag_has_no_notice(update_known) -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert "9.9.9" not in result.output
