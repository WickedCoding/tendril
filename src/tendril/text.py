from __future__ import annotations


def plural(n: int, singular: str, plural: str | None = None) -> str:
    """Format `n` with the correct singular/plural noun. E.g. `plural(1, "entry", "entries")`."""
    word = singular if n == 1 else (plural if plural is not None else singular + "s")
    return f"{n} {word}"
