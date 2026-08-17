from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: str = Field(alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = Field(default=None, alias="emailAddress")


class CommentDTO(BaseModel):
    id: str
    author: UserDTO | None = None
    body: str
    created: datetime | None = None
    updated: datetime | None = None


class LinkDTO(BaseModel):
    """One issue link as we care about it: normalized direction + target key."""

    jira_link_id: str
    link_type: str
    direction: str  # "outward" or "inward"
    target_key: str


class IssueDTO(BaseModel):
    key: str
    summary: str | None = None
    status: str | None = None
    issuetype: str | None = None
    assignee: UserDTO | None = None
    reporter: UserDTO | None = None
    created: datetime | None = None
    updated: datetime | None = None
    duedate: date | None = None
    parent_key: str | None = None
    sprint_name: str | None = None
    links: list[LinkDTO] = Field(default_factory=list)
    comments: list[CommentDTO] = Field(default_factory=list)
    raw: dict[str, Any]


ISSUE_FIELDS = ["*all"]


def _get(d: dict | None, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def _body_to_text(body: Any) -> str:
    """JIRA Cloud returns comment bodies as ADF (dict). Fall back to a JSON dump."""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return adf_to_text(body)
    return str(body) if body is not None else ""


def adf_to_text(node: dict) -> str:
    """Best-effort flatten of Atlassian Document Format to plain text."""
    parts: list[str] = []
    if node.get("type") == "text" and isinstance(node.get("text"), str):
        parts.append(node["text"])
    for child in node.get("content") or []:
        if isinstance(child, dict):
            parts.append(adf_to_text(child))
    return "".join(parts)


def _parse_user(raw: dict | None) -> UserDTO | None:
    if not raw or not raw.get("accountId"):
        return None
    return UserDTO.model_validate(raw)


def _parse_links(payload: dict) -> list[LinkDTO]:
    result: list[LinkDTO] = []
    for link in _get(payload, "fields", "issuelinks", default=[]) or []:
        type_name = _get(link, "type", "name", default="Relates") or "Relates"
        link_id = str(link.get("id", ""))
        outward = link.get("outwardIssue")
        inward = link.get("inwardIssue")
        if outward and outward.get("key"):
            result.append(LinkDTO(
                jira_link_id=link_id,
                link_type=type_name,
                direction="outward",
                target_key=outward["key"],
            ))
        if inward and inward.get("key"):
            result.append(LinkDTO(
                jira_link_id=link_id,
                link_type=type_name,
                direction="inward",
                target_key=inward["key"],
            ))
    return result


def _parse_comments(payload: dict) -> list[CommentDTO]:
    comments = _get(payload, "fields", "comment", "comments", default=[]) or []
    result: list[CommentDTO] = []
    for c in comments:
        result.append(CommentDTO(
            id=str(c.get("id", "")),
            author=_parse_user(c.get("author")),
            body=_body_to_text(c.get("body")),
            created=c.get("created"),
            updated=c.get("updated"),
        ))
    return result


def normalize_issue(payload: dict) -> IssueDTO:
    """Turn a raw `Jira.issue()` payload into a flat IssueDTO."""
    fields = payload.get("fields") or {}
    return IssueDTO(
        key=payload["key"],
        summary=fields.get("summary"),
        status=_get(fields, "status", "name"),
        issuetype=_get(fields, "issuetype", "name"),
        assignee=_parse_user(fields.get("assignee")),
        reporter=_parse_user(fields.get("reporter")),
        created=fields.get("created"),
        updated=fields.get("updated"),
        duedate=fields.get("duedate"),
        parent_key=_get(fields, "parent", "key"),
        sprint_name=None,  # populated later via configured sprint customfield id
        links=_parse_links(payload),
        comments=_parse_comments(payload),
        raw=payload,
    )
