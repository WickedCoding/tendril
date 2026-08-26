from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class SortColumn:
    """One entry the command palette can offer as a sort target."""

    key: str
    label: str


@runtime_checkable
class SortableTable(Protocol):
    """A screen whose active table exposes columns for palette-driven sorting.

    Screens that hold multiple tables should return the columns of whichever
    table is currently visible (see IssueDetailScreen's links tab).
    """

    def sort_options(self) -> Sequence[SortColumn]: ...

    def apply_sort(self, key: str, descending: bool) -> None: ...


def sort_rows(
    rows: list[Any],
    getter: Callable[[Any], Any],
    descending: bool,
) -> list[Any]:
    """Sort `rows` by `getter(row)`. `None` values are pinned to the end
    regardless of direction, so a descending sort doesn't dump the blanks
    at the top of the table.
    """
    present = [r for r in rows if getter(r) is not None]
    missing = [r for r in rows if getter(r) is None]
    present.sort(key=lambda r: _normalize(getter(r)), reverse=descending)
    return present + missing


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.casefold()
    return value
