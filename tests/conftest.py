from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tendril.db.engine import build_engine
from tendril.db.schema import init_schema

FIXTURES = Path(__file__).parent / "fixtures" / "jira"


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG_CONFIG_HOME and XDG_DATA_HOME at a tmp dir so tests can't touch real config."""
    cfg = tmp_path / "config"
    data = tmp_path / "data"
    cfg.mkdir()
    data.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    return tmp_path


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = build_engine(tmp_path / "test.db")
    init_schema(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory() as s:
        yield s


class FakeJira:
    """Minimal stand-in for `atlassian.Jira`: returns fixture payloads keyed by issue key."""

    def __init__(self, issues: dict[str, dict]) -> None:
        self._issues = issues

    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict:
        try:
            return self._issues[key]
        except KeyError as e:
            raise LookupError(f"FakeJira has no fixture for {key}") from e


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text())
    return _load


@pytest.fixture
def fake_jira_class():
    return FakeJira
