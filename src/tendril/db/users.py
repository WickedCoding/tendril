from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import User


def resolve_display_names(
    session: Session, account_ids: Iterable[str | None]
) -> dict[str, str]:
    """Return `{account_id: display_name}` for cached users with a display name.

    Missing account ids simply won't appear in the result — callers fall back to
    the raw id (or `—` when the id itself is None).
    """
    ids = {aid for aid in account_ids if aid}
    if not ids:
        return {}
    return {
        row.account_id: row.display_name
        for row in session.scalars(
            select(User).where(User.account_id.in_(ids))
        ).all()
        if row.display_name
    }


def format_user(account_id: str | None, names: dict[str, str]) -> str:
    if not account_id:
        return "—"
    return names.get(account_id, account_id)
