from __future__ import annotations

import re
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


class LinkTypeDTO(BaseModel):
    """A JIRA link type: the `name` used in write payloads plus its human phrases."""

    name: str
    outward: str
    inward: str


class SprintDTO(BaseModel):
    """One JIRA sprint as it appears on an issue's customfield.

    `state` is `"active"`, `"closed"`, or `"future"` — lowercased on parse so
    the modern (dict) and legacy (toString) shapes normalize to the same value.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    state: str
    board_id: int | None = Field(default=None, alias="boardId")
    goal: str | None = None
    start_date: datetime | None = Field(default=None, alias="startDate")
    end_date: datetime | None = Field(default=None, alias="endDate")
    complete_date: datetime | None = Field(default=None, alias="completeDate")


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
    sprints: list[SprintDTO] = Field(default_factory=list)
    links: list[LinkDTO] = Field(default_factory=list)
    comments: list[CommentDTO] = Field(default_factory=list)
    raw: dict[str, Any]


# JIRA Cloud's `POST /rest/api/3/search/jql` (enhanced_jql) returns ONLY what
# you name — `*all` there means "all navigable fields" and silently drops
# description plus every custom field. So both endpoints get explicit lists.
# Kept as two literals (not one shared list) so search vs single-issue can
# diverge later without a refactor.
#
# Config-driven custom fields (sprint id, feature-flags id) are appended per
# call via `extra_fields` in fetch.py — see sync.commands._extras_for_cfg.

SEARCH_FIELDS: list[str] = [
    "summary", "status", "issuetype",
    "assignee", "reporter",
    "created", "updated", "duedate",
    "parent", "description",
    "issuelinks", "comment",
]

ISSUE_FIELDS: list[str] = [
    "summary", "status", "issuetype",
    "assignee", "reporter",
    "created", "updated", "duedate",
    "parent", "description",
    "issuelinks", "comment",
]


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


# Legacy JIRA (pre-GDPR-migration and some on-prem tenants) returns each sprint
# as the `toString()` output of a Java object rather than a JSON object. Modern
# Cloud returns dicts. We accept both.
_LEGACY_SPRINT_RE = re.compile(r"\[(.*)\]$")


def _parse_legacy_sprint(raw: str) -> dict[str, Any] | None:
    """Parse a `com.atlassian.greenhopper.service.sprint.Sprint@…[k=v,…]` string.

    Returns the k/v pairs as a plain dict (values that are literally `<null>`
    are dropped). Returns None if the shape isn't recognised so the caller can
    skip it rather than raise.
    """
    m = _LEGACY_SPRINT_RE.search(raw)
    if m is None:
        return None
    result: dict[str, Any] = {}
    for pair in m.group(1).split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        v = v.strip()
        if v == "<null>" or v == "":
            continue
        result[k.strip()] = v
    if "id" not in result or "name" not in result or "state" not in result:
        return None
    return result


def _parse_sprints(payload: dict, field_id: str | None) -> list[SprintDTO]:
    """Extract the configured sprint customfield into `SprintDTO`s.

    No field_id (unconfigured) or field missing/null → empty list. Handles both
    the modern list-of-dicts and legacy list-of-toString-strings shapes.
    """
    if not field_id:
        return []
    raw = _get(payload, "fields", field_id, default=None)
    if not raw:
        return []
    out: list[SprintDTO] = []
    for item in raw:
        if isinstance(item, dict):
            data = dict(item)
        elif isinstance(item, str):
            parsed = _parse_legacy_sprint(item)
            if parsed is None:
                continue
            data = parsed
        else:
            continue
        state = data.get("state")
        if isinstance(state, str):
            data["state"] = state.lower()
        try:
            out.append(SprintDTO.model_validate(data))
        except Exception:
            continue
    return out


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


def normalize_issue(payload: dict, sprint_field_id: str | None = None) -> IssueDTO:
    """Turn a raw `Jira.issue()` payload into a flat IssueDTO.

    `sprint_field_id` is the configured customfield id (e.g. `customfield_10020`);
    when None, sprints stays empty regardless of what the payload carries.
    """
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
        sprints=_parse_sprints(payload, sprint_field_id),
        links=_parse_links(payload),
        comments=_parse_comments(payload),
        raw=payload,
    )
