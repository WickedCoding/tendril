"""Live integration tests. Opt-in only.

These hit the real JIRA instance configured at `~/.config/tendril/config.toml`.
They are skipped unless `TENDRIL_LIVE=1` is set. Read-only by default — you can
add mutation tests locally against a sandbox project.

Required env:
  TENDRIL_LIVE=1             enable the suite
  TENDRIL_LIVE_ISSUE=KEY-123  a real, readable issue key on your instance

Example:
  TENDRIL_LIVE=1 TENDRIL_LIVE_ISSUE=MMINT-1 uv run pytest tests/integration
"""

from __future__ import annotations

import os

import pytest

from tendril import config as cfg_mod
from tendril.db.engine import build_engine, session_factory
from tendril.db.schema import init_schema
from tendril.jira import client as jira_client
from tendril.sync.commands import sync_issue

pytestmark = pytest.mark.skipif(
    os.environ.get("TENDRIL_LIVE") != "1",
    reason="live JIRA tests are opt-in; set TENDRIL_LIVE=1 to enable",
)


@pytest.fixture(scope="module")
def live_client():
    cfg = cfg_mod.load()
    return jira_client.build(cfg)


@pytest.fixture(scope="module")
def live_issue_key() -> str:
    key = os.environ.get("TENDRIL_LIVE_ISSUE")
    if not key:
        pytest.skip("Set TENDRIL_LIVE_ISSUE to a readable issue key on your instance.")
    return key


def test_whoami_returns_display_name(live_client) -> None:
    me = jira_client.myself(live_client)
    assert me.get("displayName"), me


def test_sync_issue_populates_cache(tmp_path, live_client, live_issue_key) -> None:
    engine = build_engine(tmp_path / "live.db")
    init_schema(engine)
    with session_factory(engine)() as session:
        row = sync_issue(live_client, session, live_issue_key)
    # JIRA may have moved the issue; both original and current key are acceptable.
    assert row.key
    assert row.summary is not None
