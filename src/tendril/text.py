from __future__ import annotations

from datetime import datetime


def plural(n: int, singular: str, plural: str | None = None) -> str:
    """Format `n` with the correct singular/plural noun. E.g. `plural(1, "entry", "entries")`."""
    word = singular if n == 1 else (plural if plural is not None else singular + "s")
    return f"{n} {word}"


def local_time(dt: datetime | None, missing: str = "—") -> str:
    """Render a stored (UTC) timestamp in the machine's local timezone, to the minute."""
    if dt is None:
        return missing
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
