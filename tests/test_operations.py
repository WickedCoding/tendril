from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import Comment, Issue, IssueLink
from tendril.jira.dto import normalize_issue
from tendril.operations import ops
from tendril.sync.pipeline import upsert_issue


class FakeOpsJira:
    """Fake JIRA client for tests.

    Records write calls and mutates a mutable fixture payload so the follow-up
    refetch (`sync_issue`) sees the change.
    """

    def __init__(self, issues: dict[str, dict]) -> None:
        self._issues = deepcopy(issues)
        self.calls: list[tuple[str, tuple, dict]] = []
        self._next_comment_id = 40000
        self._next_link_id = 60000

    # ---- read side ----
    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict:
        return self._issues[key]

    def enhanced_jql(self, *a, **kw):
        raise AssertionError("write-side tests should not paginate")

    # ---- write side ----
    def issue_add_comment(self, key: str, body: str, visibility=None):
        self.calls.append(("add_comment", (key, body), {}))
        cid = str(self._next_comment_id)
        self._next_comment_id += 1
        self._issues[key]["fields"].setdefault("comment", {"comments": []})
        self._issues[key]["fields"]["comment"]["comments"].append({
            "id": cid,
            "author": {"accountId": "acc-me", "displayName": "Me"},
            "body": body,
            "created": "2026-08-17T09:00:00.000+0000",
            "updated": "2026-08-17T09:00:00.000+0000",
        })
        return {"id": cid}

    def create_issue_link(self, data: dict):
        self.calls.append(("create_link", (data,), {}))
        link_id = str(self._next_link_id)
        self._next_link_id += 1
        outward_key = data["outwardIssue"]["key"]
        inward_key = data["inwardIssue"]["key"]
        link_type = data["type"]["name"]
        # Mirror the link into both fixture sides that we happen to have.
        # Tests without every referenced issue in the store still exercise the wire call.
        if outward_key in self._issues:
            self._issues[outward_key]["fields"].setdefault("issuelinks", []).append({
                "id": link_id,
                "type": {"name": link_type},
                "outwardIssue": {"key": inward_key},
            })
        if inward_key in self._issues:
            self._issues[inward_key]["fields"].setdefault("issuelinks", []).append({
                "id": link_id,
                "type": {"name": link_type},
                "inwardIssue": {"key": outward_key},
            })
        return {"id": link_id}

    def remove_issue_link(self, link_id):
        self.calls.append(("remove_link", (link_id,), {}))
        for issue in self._issues.values():
            links = issue["fields"].get("issuelinks") or []
            issue["fields"]["issuelinks"] = [l for l in links if str(l.get("id")) != str(link_id)]
        return None

    def update_issue_field(self, key, fields, notify_users=True):
        self.calls.append(("update_field", (key, fields), {}))
        self._issues[key]["fields"].update(fields)
        return None


@pytest.fixture
def seeded(session: Session, load_fixture):
    upsert_issue(session, normalize_issue(load_fixture("issue_sample.json")))
    session.commit()
    return session


def _client(load_fixture) -> FakeOpsJira:
    return FakeOpsJira({"PROJ-1": load_fixture("issue_sample.json")})


def test_add_comment_writes_then_refreshes_cache(seeded: Session, load_fixture) -> None:
    client = _client(load_fixture)
    before = seeded.query(Comment).filter(Comment.issue_key == "PROJ-1").count()
    ops.add_comment(client, seeded, "PROJ-1", "Fresh comment.")
    after = seeded.query(Comment).filter(Comment.issue_key == "PROJ-1").count()
    assert after == before + 1
    assert client.calls[0][0] == "add_comment"
    # confirm the new comment made it into the cache with the body we sent
    fresh = seeded.scalars(select(Comment).where(Comment.issue_key == "PROJ-1")).all()
    assert any(c.body == "Fresh comment." for c in fresh)


def test_create_link_outward_writes_source_as_outward_issue(
    seeded: Session, load_fixture
) -> None:
    client = _client(load_fixture)
    ops.create_link(client, seeded, "PROJ-1", "PROJ-999", "Blocks", "outward")
    assert client.calls[0][0] == "create_link"
    data = client.calls[0][1][0]
    assert data["outwardIssue"]["key"] == "PROJ-1"
    assert data["inwardIssue"]["key"] == "PROJ-999"
    links = seeded.scalars(select(IssueLink).where(IssueLink.source_key == "PROJ-1")).all()
    assert any(
        l.target_key == "PROJ-999" and l.direction == "outward" and l.link_type == "Blocks"
        for l in links
    )


def test_create_link_inward_flips_source_and_target_on_the_wire(
    seeded: Session, load_fixture
) -> None:
    """`inward` means source uses the inward phrase → source becomes the inwardIssue in JIRA."""
    client = _client(load_fixture)
    ops.create_link(client, seeded, "PROJ-1", "PROJ-999", "Blocks", "inward")
    data = client.calls[0][1][0]
    assert data["outwardIssue"]["key"] == "PROJ-999"
    assert data["inwardIssue"]["key"] == "PROJ-1"


def test_create_link_rejects_unknown_direction(seeded: Session, load_fixture) -> None:
    client = _client(load_fixture)
    with pytest.raises(ValueError, match="direction"):
        ops.create_link(client, seeded, "PROJ-1", "PROJ-999", "Blocks", "sideways")


def test_delete_link_removes_and_refreshes(seeded: Session, load_fixture) -> None:
    client = _client(load_fixture)
    # Fixture already carries link 20001 (Blocks → PROJ-2) — remove it.
    before = {l.jira_link_id for l in seeded.scalars(select(IssueLink)).all()}
    assert "20001" in before

    ops.delete_link(client, seeded, "PROJ-1", "20001")
    after = {l.jira_link_id for l in seeded.scalars(select(IssueLink)).all()}
    assert "20001" not in after
    assert client.calls[0][0] == "remove_link"


def test_set_feature_flags_writes_labels_payload_and_refreshes(
    seeded: Session, load_fixture
) -> None:
    client = _client(load_fixture)
    ops.set_feature_flags(client, seeded, "PROJ-1", "customfield_10457", ["exp_a", "exp_b"])
    call = client.calls[0]
    assert call[0] == "update_field"
    _, fields = call[1]
    # Field is a labels-type custom field: array of strings, not [{value: ...}].
    assert fields == {"customfield_10457": ["exp_a", "exp_b"]}

    issue = seeded.get(Issue, "PROJ-1")
    assert ops.read_feature_flags(issue.raw_json, "customfield_10457") == ["exp_a", "exp_b"]


def test_set_feature_flags_empty_list_clears_all(seeded: Session, load_fixture) -> None:
    """Empty list clears the field — labels fields accept `[]` to remove all values."""
    client = _client(load_fixture)
    ops.set_feature_flags(client, seeded, "PROJ-1", "customfield_10457", [])
    _, fields = client.calls[0][1]
    assert fields == {"customfield_10457": []}


def test_read_feature_flags_handles_multiple_shapes() -> None:
    multi = {"fields": {"cf": [{"value": "a"}, {"value": "b"}]}}
    labels = {"fields": {"cf": ["x", "y"]}}
    scalar = {"fields": {"cf": "solo"}}
    missing = {"fields": {}}
    assert ops.read_feature_flags(multi, "cf") == ["a", "b"]
    assert ops.read_feature_flags(labels, "cf") == ["x", "y"]
    assert ops.read_feature_flags(scalar, "cf") == ["solo"]
    assert ops.read_feature_flags(missing, "cf") == []
