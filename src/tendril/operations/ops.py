from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from tendril.config import Config
from tendril.db.models import (
    Issue,
    ROLLOVER_STEP_CLOSE,
    ROLLOVER_STEP_MOVE,
    ROLLOVER_STEP_START,
    RolloverAttempt,
    RolloverLog,
    Sprint,
)
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


# ---------- sprint rollover ----------


def start_rollover(
    session: Session,
    *,
    source_sprint_id: int,
    target_sprint_id: int,
    selected_keys: list[str],
) -> RolloverAttempt:
    """Create or refresh the RolloverAttempt row for `source_sprint_id`.

    A pre-existing row (from a partial rollover) keeps its `moved_issue_keys`
    and `completed_step` so a resume picks up where the last try failed. The
    target sprint id and the selection are refreshed from the caller so the
    user can revise the plan between failed attempts.
    """
    now = datetime.now(timezone.utc)
    existing = session.get(RolloverAttempt, source_sprint_id)
    if existing is None:
        existing = RolloverAttempt(
            source_sprint_id=source_sprint_id,
            target_sprint_id=target_sprint_id,
            selected_issue_keys=list(selected_keys),
            moved_issue_keys=[],
            completed_step=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        session.add(existing)
    else:
        existing.target_sprint_id = target_sprint_id
        existing.selected_issue_keys = list(selected_keys)
        existing.error = None
        existing.updated_at = now
    session.commit()
    return existing


def execute_rollover(
    client: OpsJira,
    session: Session,
    *,
    source_sprint_id: int,
    source_sprint_name: str,
    target_sprint_name: str,
    cfg: Config | None = None,
) -> RolloverLog:
    """Advance the rollover attempt for `source_sprint_id` through remaining steps.

    Requires a prior `start_rollover` call. Executes the four steps in strict
    order — move issues, close source, start target, log — persisting progress
    on the `RolloverAttempt` between each. On JIRA failure the step's error is
    recorded, the exception re-raised, and the row survives for a later resume.
    On success the attempt row is deleted and a `RolloverLog` row is written.
    """
    attempt = session.get(RolloverAttempt, source_sprint_id)
    if attempt is None:
        raise ValueError(
            f"No RolloverAttempt for source sprint {source_sprint_id}. "
            "Call start_rollover first."
        )

    try:
        if attempt.completed_step is None:
            _step_move(client, session, attempt, cfg=cfg)
        if attempt.completed_step == ROLLOVER_STEP_MOVE:
            _step_close_source(client, session, attempt)
        if attempt.completed_step == ROLLOVER_STEP_CLOSE:
            _step_start_target(client, session, attempt)
    except Exception as e:  # noqa: BLE001 — record the message so resume can show it
        attempt.error = str(e)
        attempt.updated_at = datetime.now(timezone.utc)
        session.commit()
        raise

    # All three write steps done. Log the success and clear the attempt.
    now = datetime.now(timezone.utc)
    log = RolloverLog(
        source_sprint_id=attempt.source_sprint_id,
        source_sprint_name=source_sprint_name,
        target_sprint_id=attempt.target_sprint_id,
        target_sprint_name=target_sprint_name,
        moved_issue_keys=list(attempt.moved_issue_keys),
        committed_at=now,
    )
    session.add(log)
    session.delete(attempt)
    session.commit()
    return log


def _step_move(
    client: OpsJira,
    session: Session,
    attempt: RolloverAttempt,
    cfg: Config | None,
) -> None:
    """Step 1: move every selected issue into the target sprint, refetch each.

    The JIRA endpoint is idempotent, so resending keys that already sit in the
    target (from a previously-succeeded partial call) is safe.
    """
    keys = list(attempt.selected_issue_keys)
    if keys:
        jw.move_issues_to_sprint(client, attempt.target_sprint_id, keys)
        # Refetch each moved issue to keep the cache honest (invariant: every
        # write refetches). Loop over sync_issue so a single-issue lookup still
        # applies the rename-migration path if JIRA moved the key server-side.
        for key in keys:
            sync_issue(client, session, key, cfg=cfg)
    attempt.moved_issue_keys = list(keys)
    attempt.completed_step = ROLLOVER_STEP_MOVE
    attempt.updated_at = datetime.now(timezone.utc)
    session.commit()


def _step_close_source(
    client: OpsJira,
    session: Session,
    attempt: RolloverAttempt,
) -> None:
    """Step 2: close the source sprint. Local cache follows JIRA's new state."""
    jw.close_sprint(client, attempt.source_sprint_id)
    source = session.get(Sprint, attempt.source_sprint_id)
    if source is not None:
        source.state = "closed"
    attempt.completed_step = ROLLOVER_STEP_CLOSE
    attempt.updated_at = datetime.now(timezone.utc)
    session.commit()


def _step_start_target(
    client: OpsJira,
    session: Session,
    attempt: RolloverAttempt,
) -> None:
    """Step 3: activate the target sprint. The target must already have dates."""
    jw.start_sprint(client, attempt.target_sprint_id)
    target = session.get(Sprint, attempt.target_sprint_id)
    if target is not None:
        target.state = "active"
    attempt.completed_step = ROLLOVER_STEP_START
    attempt.updated_at = datetime.now(timezone.utc)
    session.commit()
