"""Once-a-day check for a newer tendril release on PyPI.

The result is cached in `version-check.toml` next to `config.toml`, so only the
first command of the day touches the network. Every failure (offline, bad JSON,
unwritable state file) degrades to "no update known" — a version check must
never break a command.
"""
from __future__ import annotations

import json
import os
import tomllib
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Callable

import tomli_w
from packaging.version import InvalidVersion, Version

from tendril import config as cfg_mod

PACKAGE = "tendril-jira"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
CHECK_INTERVAL = timedelta(days=1)
DISABLE_ENV = "TENDRIL_NO_VERSION_CHECK"


def state_path() -> Path:
    return cfg_mod.config_dir() / "version-check.toml"


def installed_version() -> str:
    return _pkg_version(PACKAGE)


def fetch_latest(timeout: float = 2.0) -> str | None:
    """Latest released version according to PyPI, or None on any failure."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=timeout) as resp:
            return str(json.load(resp)["info"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _read_state() -> dict:
    try:
        with state_path().open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _write_state(state: dict) -> None:
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            tomli_w.dump(state, f)
    except OSError:
        pass


def _is_fresh(state: dict, now: datetime) -> bool:
    try:
        checked_at = datetime.fromisoformat(state["checked_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if checked_at.tzinfo is None:
        return False
    return now - checked_at < CHECK_INTERVAL


def _is_newer(latest: str, installed: str) -> bool:
    try:
        return Version(latest) > Version(installed)
    except InvalidVersion:
        return False


def check(
    now: datetime | None = None,
    fetch: Callable[[], str | None] = fetch_latest,
) -> str | None:
    """Return the newer PyPI version if one exists, else None.

    Hits PyPI at most once per `CHECK_INTERVAL`; a failed fetch still stamps
    `checked_at` so an offline machine waits for the timeout once a day, not
    on every command. Compares against the installed version at call time, so
    the notice disappears right after an upgrade.
    """
    if os.environ.get(DISABLE_ENV):
        return None
    now = now or datetime.now(timezone.utc)
    installed = installed_version()
    state = _read_state()
    latest = state.get("latest")
    if not _is_fresh(state, now):
        latest = fetch() or latest
        new_state = {"checked_at": now.isoformat(timespec="seconds"), "current": installed}
        if isinstance(latest, str):
            new_state["latest"] = latest
        _write_state(new_state)
    if not isinstance(latest, str):
        return None
    return latest if _is_newer(latest, installed) else None


def notice(latest: str) -> str:
    return (
        f"tendril {latest} is available (installed {installed_version()}). "
        f"Upgrade: uv tool upgrade {PACKAGE}"
    )
