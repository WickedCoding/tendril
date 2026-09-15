from __future__ import annotations

from typing import Any, Protocol


class JiraWriteLike(Protocol):
    def issue_add_comment(self, issue_key: str, comment: str, visibility: dict | None = None) -> Any: ...
    def create_issue_link(self, data: dict) -> Any: ...
    def remove_issue_link(self, link_id: str | int) -> Any: ...
    def update_issue_field(self, key: str, fields: dict, notify_users: bool = True) -> Any: ...
    def add_issues_to_sprint(self, sprint_id: int, issues: list[str]) -> Any: ...
    def update_partially_sprint(self, sprint_id: int, data: dict) -> Any: ...


def add_comment(client: JiraWriteLike, key: str, body: str) -> Any:
    return client.issue_add_comment(key, body)


def move_issues_to_sprint(
    client: JiraWriteLike,
    sprint_id: int,
    keys: list[str],
) -> Any:
    """Batch-move issues into a sprint via the Agile API.

    JIRA accepts up to 50 keys per call; callers who need to move more should
    chunk. The endpoint is idempotent: re-sending a key that already sits in
    the sprint is a no-op, which makes step-1 retries on partial failure safe.
    """
    return client.add_issues_to_sprint(sprint_id, list(keys))


def close_sprint(client: JiraWriteLike, sprint_id: int) -> Any:
    """Transition a sprint from active → closed. JIRA expects `state=closed`."""
    return client.update_partially_sprint(sprint_id, {"state": "closed"})


def start_sprint(client: JiraWriteLike, sprint_id: int) -> Any:
    """Transition a sprint from future → active.

    JIRA requires `startDate` and `endDate` set on the sprint before it can
    be started, but the sprint is expected to have them (Tendril never creates
    sprints — the user set them up in JIRA). Any refusal surfaces as an
    exception the ops layer records on the RolloverAttempt.
    """
    return client.update_partially_sprint(sprint_id, {"state": "active"})


def create_link(client: JiraWriteLike, type_name: str, outward_key: str, inward_key: str) -> Any:
    """Create a link between two issues.

    JIRA's link semantics: `outward_key <outward-phrase> inward_key`. E.g. for
    type "Blocks", `outward_key blocks inward_key`. Callers translate the user's
    chosen direction into (outward_key, inward_key) before calling.
    """
    data = {
        "type": {"name": type_name},
        "outwardIssue": {"key": outward_key},
        "inwardIssue": {"key": inward_key},
    }
    return client.create_issue_link(data)


def remove_link(client: JiraWriteLike, link_id: str) -> Any:
    return client.remove_issue_link(link_id)


def update_field(client: JiraWriteLike, key: str, field_id: str, value: Any) -> Any:
    return client.update_issue_field(key, {field_id: value})
