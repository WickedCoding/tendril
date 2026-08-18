from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import LinkType
from tendril.sync.commands import sync_link_types


BLOCKS = {"id": "10000", "name": "Blocks", "outward": "blocks", "inward": "is blocked by"}
RELATES = {"id": "10001", "name": "Relates", "outward": "relates to", "inward": "relates to"}
CLONERS = {"id": "10002", "name": "Cloners", "outward": "clones", "inward": "is cloned by"}


def _client(link_types, fake_jira_class):
    return fake_jira_class(issues={}, link_types=link_types)


def test_sync_link_types_populates_empty_table(session: Session, fake_jira_class) -> None:
    client = _client([BLOCKS, RELATES], fake_jira_class)
    rows = sync_link_types(client, session)

    assert {r.name for r in rows} == {"Blocks", "Relates"}
    blocks = session.get(LinkType, "Blocks")
    assert blocks is not None
    assert blocks.outward == "blocks"
    assert blocks.inward == "is blocked by"


def test_sync_link_types_replaces_wholesale(session: Session, fake_jira_class) -> None:
    """A second sync with a different list overwrites the table entirely."""
    sync_link_types(_client([BLOCKS, RELATES], fake_jira_class), session)
    sync_link_types(_client([CLONERS], fake_jira_class), session)

    names = {r.name for r in session.scalars(select(LinkType)).all()}
    assert names == {"Cloners"}


def test_sync_link_types_handles_empty_response(session: Session, fake_jira_class) -> None:
    session.add(LinkType(name="Stale", outward="stales", inward="is staled by"))
    session.commit()
    sync_link_types(_client([], fake_jira_class), session)
    assert session.scalars(select(LinkType)).all() == []
