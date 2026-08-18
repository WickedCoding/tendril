from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from tendril.config import Config
from tendril.db.models import Issue
from tendril.jira import write as jw
from tendril.jira.fetch import JiraLike
from tendril.sync.commands import sync_issue


class OpsJira(JiraLike, jw.JiraWriteLike, Protocol):
    """Client capable of both reads (fetch) and writes (add/link/update)."""


def add_comment(
    client: OpsJira,
    session: Session,
    key: str,
    body: str,
    cfg: Config | None = None,
) -> Issue:
    """Post a comment to JIRA and refresh the issue in the local cache."""
    jw.add_comment(client, key, body)
    return sync_issue(client, session, key, cfg=cfg)


def create_link(
    client: OpsJira,
    session: Session,
    source_key: str,
    target_key: str,
    type_name: str,
    direction: str,
    cfg: Config | None = None,
) -> Issue:
    """Create a link from `source_key` to `target_key` and refresh the source in the cache.

    `direction` reads from the source's perspective: `"outward"` means the source
    uses the outward phrase (e.g. `source blocks target` for type "Blocks");
    `"inward"` means the source uses the inward phrase (e.g. `source is blocked by target`).

    The target is not refreshed automatically — the user can open it and press `r` if needed.
    """
    if direction == "outward":
        outward, inward = source_key, target_key
    elif direction == "inward":
        outward, inward = target_key, source_key
    else:
        raise ValueError(f"direction must be 'outward' or 'inward', got {direction!r}")
    jw.create_link(client, type_name, outward, inward)
    return sync_issue(client, session, source_key, cfg=cfg)


def delete_link(
    client: OpsJira,
    session: Session,
    source_key: str,
    jira_link_id: str,
    cfg: Config | None = None,
) -> Issue:
    """Remove a link and refresh the source in the cache."""
    jw.remove_link(client, jira_link_id)
    return sync_issue(client, session, source_key, cfg=cfg)


def set_feature_flags(
    client: OpsJira,
    session: Session,
    key: str,
    field_id: str,
    values: list[str],
    cfg: Config | None = None,
) -> Issue:
    """Overwrite the feature-flags labels custom field.

    Field schema is `array of string` (JIRA labels custom-field type), so the
    payload is a plain list of strings. Empty list clears all flags.
    """
    jw.update_field(client, key, field_id, list(values))
    return sync_issue(client, session, key, cfg=cfg)


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
