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
    """Minimal stand-in for `atlassian.Jira`: returns fixture payloads keyed by issue key.

    Speaks the enhanced_jql contract: token-based pagination via `nextPageToken` + `isLast`.
    Supports the small JQL subset our production code emits:
      - `key in (A,B,C)` — returns matching fixtures
      - `project = "X"` — returns fixtures whose key starts with "X-"
      - `updated >= "..."` — captured but ignored
    """

    def __init__(
        self,
        issues: dict[str, dict],
        link_types: list[dict] | None = None,
    ) -> None:
        self._issues = issues
        self._link_types = link_types or []
        self.jql_calls: list[str] = []

    def get_issue_link_types(self) -> dict:
        return {"issueLinkTypes": list(self._link_types)}

    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict:
        try:
            return self._issues[key]
        except KeyError as e:
            raise LookupError(f"FakeJira has no fixture for {key}") from e

    def enhanced_jql(
        self,
        jql: str,
        fields: str | list[str] = "*all",
        nextPageToken: str | None = None,
        limit: int | None = None,
        expand: str | None = None,
    ) -> dict:
        self.jql_calls.append(jql)
        matched: list[dict]
        keys = self._parse_key_in(jql)
        project = self._parse_project_eq(jql)
        if keys is not None:
            matched = [self._issues[k] for k in keys if k in self._issues]
        elif project is not None:
            matched = [i for i in self._issues.values() if i["key"].startswith(f"{project}-")]
        else:
            matched = list(self._issues.values())

        start = int(nextPageToken) if nextPageToken else 0
        page_size = limit or 50
        page = matched[start : start + page_size]
        next_start = start + len(page)
        is_last = next_start >= len(matched)
        return {
            "issues": page,
            "isLast": is_last,
            "nextPageToken": None if is_last else str(next_start),
        }

    @staticmethod
    def _parse_key_in(jql: str) -> list[str] | None:
        marker = "key in ("
        i = jql.find(marker)
        if i < 0:
            return None
        j = jql.find(")", i)
        inside = jql[i + len(marker) : j]
        return [k.strip().strip('"') for k in inside.split(",") if k.strip()]

    @staticmethod
    def _parse_project_eq(jql: str) -> str | None:
        marker = "project = "
        i = jql.find(marker)
        if i < 0:
            return None
        tail = jql[i + len(marker) :].lstrip()
        if tail.startswith('"'):
            end = tail.find('"', 1)
            return tail[1:end] if end > 0 else None
        end = 0
        while end < len(tail) and (tail[end].isalnum() or tail[end] == "_"):
            end += 1
        return tail[:end] or None


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text())
    return _load


@pytest.fixture
def fake_jira_class():
    return FakeJira
