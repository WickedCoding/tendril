from __future__ import annotations

from typing import Any, Iterable, Protocol

from tendril.jira.dto import ISSUE_FIELDS, IssueDTO, normalize_issue

JQL_CHUNK = 50


class JiraLike(Protocol):
    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict[str, Any]: ...
    def enhanced_jql(
        self,
        jql: str,
        fields: str | list[str] = "*all",
        nextPageToken: str | None = None,
        limit: int | None = None,
        expand: str | None = None,
    ) -> dict[str, Any]: ...


def fetch_issue(client: JiraLike, key: str) -> IssueDTO:
    """Fetch a single issue with links and comments, normalized to an IssueDTO."""
    payload = client.issue(key, fields=",".join(ISSUE_FIELDS))
    return normalize_issue(payload)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def search_by_keys(client: JiraLike, keys: list[str]) -> list[IssueDTO]:
    """Fetch many issues by key via JQL, chunking the key list to stay within request limits."""
    out: list[IssueDTO] = []
    for chunk in _chunks(keys, JQL_CHUNK):
        out.extend(search_by_jql(client, jql_key_in(chunk)))
    return out


def jql_key_in(keys: list[str]) -> str:
    """Build a JQL `key in (...)` clause. Empty input yields a clause that matches nothing."""
    if not keys:
        return "key in (NONEXISTENT-0)"
    quoted = ",".join(keys)
    return f"key in ({quoted})"


def search_by_jql(client: JiraLike, jql: str) -> list[IssueDTO]:
    """Run a JQL query and return normalized DTOs, paginating until exhausted.

    Uses JIRA Cloud's token-based pagination (`enhanced_jql`): each response
    carries `nextPageToken` + `isLast`, replacing the deprecated `startAt/total` shape.
    """
    fields = ",".join(ISSUE_FIELDS)
    out: list[IssueDTO] = []
    token: str | None = None
    while True:
        page = client.enhanced_jql(jql, fields=fields, nextPageToken=token, limit=JQL_CHUNK)
        issues = page.get("issues") or []
        out.extend(normalize_issue(p) for p in issues)
        if page.get("isLast"):
            break
        token = page.get("nextPageToken")
        if not token:
            break
    return out
