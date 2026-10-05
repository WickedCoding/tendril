from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.db.models import LinkType


def link_phrases(session: Session) -> dict[str, tuple[str, str]]:
    """Return `{link_type_name: (outward, inward)}` for every cached link type."""
    return {
        lt.name: (lt.outward, lt.inward)
        for lt in session.scalars(select(LinkType)).all()
    }


def link_phrase(
    link_type: str,
    direction: str,
    phrases: dict[str, tuple[str, str]],
) -> str:
    """Human phrase for one side of a link, e.g. `blocks` / `is blocked by`.

    Uses the cached outward/inward phrase for the link type; falls back to the
    raw API name plus a direction arrow if the type isn't cached (run
    `tendril sync link-types` to fix).
    """
    if link_type in phrases:
        outward, inward = phrases[link_type]
        return outward if direction == "outward" else inward
    arrow = "→" if direction == "outward" else "←"
    return f"{link_type} {arrow}"
