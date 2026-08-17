from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from tendril.db.models import Issue
from tendril.jira import write as jw
from tendril.jira.fetch import JiraLike
from tendril.sync.commands import sync_issue


class OpsJira(JiraLike, jw.JiraWriteLike, Protocol):
    """Client capable of both reads (fetch) and writes (add/link/update)."""


def add_comment(client: OpsJira, session: Session, key: str, body: str) -> Issue:
    """Post a comment to JIRA and refresh the issue in the local cache."""
    jw.add_comment(client, key, body)
    return sync_issue(client, session, key)


def create_link(
    client: OpsJira,
    session: Session,
    source_key: str,
    target_key: str,
    link_type: str,
) -> Issue:
    """Create `source --link_type--> target` in JIRA and refresh the source in the cache.

    The target is not refreshed automatically — the user can open it and press `r` if needed.
    """
    jw.create_link(client, link_type, source_key, target_key)
    return sync_issue(client, session, source_key)


def delete_link(client: OpsJira, session: Session, source_key: str, jira_link_id: str) -> Issue:
    """Remove a link and refresh the source in the cache."""
    jw.remove_link(client, jira_link_id)
    return sync_issue(client, session, source_key)


def set_feature_flags(
    client: OpsJira,
    session: Session,
    key: str,
    field_id: str,
    values: list[str],
) -> Issue:
    """Overwrite the feature-flags labels custom field.

    Field schema is `array of string` (JIRA labels custom-field type), so the
    payload is a plain list of strings. Empty list clears all flags.
    """
    jw.update_field(client, key, field_id, list(values))
    return sync_issue(client, session, key)


def read_feature_flags(raw_json: dict, field_id: str) -> list[str]:
    """Extract feature-flag values from the raw JIRA payload.

    Handles the common shapes: list of `{value: ...}` dicts (multi-select) and list of strings.
    """
    value = ((raw_json or {}).get("fields") or {}).get(field_id)
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                v = item.get("value") or item.get("name")
                if v is not None:
                    out.append(str(v))
            elif isinstance(item, str):
                out.append(item)
        return out
    if isinstance(value, str):
        return [value]
    return []
