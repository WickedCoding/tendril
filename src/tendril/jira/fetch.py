from __future__ import annotations

from typing import Any, Protocol

from tendril.jira.dto import ISSUE_FIELDS, IssueDTO, normalize_issue


class JiraLike(Protocol):
    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict[str, Any]: ...


def fetch_issue(client: JiraLike, key: str) -> IssueDTO:
    """Fetch a single issue with links and comments, normalized to an IssueDTO."""
    payload = client.issue(key, fields=",".join(ISSUE_FIELDS))
    return normalize_issue(payload)
