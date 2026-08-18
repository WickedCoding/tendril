from __future__ import annotations

from typing import Any, Protocol


class JiraWriteLike(Protocol):
    def issue_add_comment(self, issue_key: str, comment: str, visibility: dict | None = None) -> Any: ...
    def create_issue_link(self, data: dict) -> Any: ...
    def remove_issue_link(self, link_id: str | int) -> Any: ...
    def update_issue_field(self, key: str, fields: dict, notify_users: bool = True) -> Any: ...


def add_comment(client: JiraWriteLike, key: str, body: str) -> Any:
    return client.issue_add_comment(key, body)


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
