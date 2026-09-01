from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tendril.db.models import Issue, IssueTag
from tendril.tags import ops
from tendril.tags.matcher import find_surfaces


def _issue(session: Session, key: str, summary: str = "") -> Issue:
    row = Issue(
        key=key,
        summary=summary,
        raw_json={"key": key, "fields": {}},
        last_synced_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row


class TestTagOps:
    def test_add_is_idempotent(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo", "branding"])
        ops.add_tags(session, "PROJ-1", ["logo", "carousel"])
        assert ops.list_tags_for(session, "PROJ-1") == ["branding", "carousel", "logo"]

    def test_add_normalizes_and_dedupes(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["  logo  ", "logo", "", "branding"])
        assert ops.list_tags_for(session, "PROJ-1") == ["branding", "logo"]

    def test_remove_returns_deleted_count(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo", "branding", "carousel"])
        n = ops.remove_tags(session, "PROJ-1", ["logo", "gone"])
        assert n == 1
        assert ops.list_tags_for(session, "PROJ-1") == ["branding", "carousel"]

    def test_set_replaces_full_set(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo", "branding"])
        ops.set_tags(session, "PROJ-1", ["deal-placement"])
        assert ops.list_tags_for(session, "PROJ-1") == ["deal-placement"]

    def test_set_empty_clears(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.set_tags(session, "PROJ-1", [])
        assert ops.list_tags_for(session, "PROJ-1") == []

    def test_list_all_tagged(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-2")
        ops.add_tags(session, "PROJ-2", ["carousel"])
        ops.add_tags(session, "PROJ-1", ["logo", "branding"])
        assert ops.list_all_tagged(session) == [
            ("PROJ-1", ["branding", "logo"]),
            ("PROJ-2", ["carousel"]),
        ]


class TestFindSurfaces:
    def test_returns_empty_when_viewed_has_no_tags(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-2", "logo blocker")
        ops.add_tags(session, "PROJ-2", ["logo"])
        assert find_surfaces(session, "PROJ-1") == []

    def test_shared_tag_surfaces_by_default(self, session: Session) -> None:
        """Every tagged issue with a shared tag surfaces — no opt-in marker."""
        _issue(session, "PROJ-1", "logo blocker")
        _issue(session, "PROJ-2", "add logo to layout")
        ops.add_tags(session, "PROJ-1", ["logo", "branding"])
        ops.add_tags(session, "PROJ-2", ["logo", "deal-placement"])

        surfaces = find_surfaces(session, "PROJ-2")
        assert len(surfaces) == 1
        surfaced_issue, shared_tags = surfaces[0]
        assert surfaced_issue.key == "PROJ-1"
        assert shared_tags == ["logo"]

    def test_never_surfaces_self(self, session: Session) -> None:
        _issue(session, "PROJ-1", "logo blocker")
        _issue(session, "PROJ-2", "unrelated")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.add_tags(session, "PROJ-2", ["logo"])
        surfaces = find_surfaces(session, "PROJ-1")
        keys = [i.key for i, _ in surfaces]
        assert "PROJ-1" not in keys

    def test_multiple_shared_tags_are_all_reported(self, session: Session) -> None:
        _issue(session, "PROJ-1", "logo + branding")
        _issue(session, "PROJ-2", "logo + branding")
        ops.add_tags(session, "PROJ-1", ["logo", "branding", "carousel"])
        ops.add_tags(session, "PROJ-2", ["logo", "branding", "deal-placement"])

        surfaces = find_surfaces(session, "PROJ-2")
        assert len(surfaces) == 1
        _, shared_tags = surfaces[0]
        assert sorted(shared_tags) == ["branding", "logo"]

    def test_orders_multiple_surfaces_by_issue_key(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-10", "later")
        _issue(session, "PROJ-2", "earlier")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.add_tags(session, "PROJ-2", ["logo"])
        ops.add_tags(session, "PROJ-10", ["logo"])

        surfaces = find_surfaces(session, "PROJ-1")
        keys = [i.key for i, _ in surfaces]
        assert keys == ["PROJ-10", "PROJ-2"]

    def test_untagged_issue_does_not_surface(self, session: Session) -> None:
        _issue(session, "PROJ-1", "no tags")
        _issue(session, "PROJ-2")
        ops.add_tags(session, "PROJ-2", ["logo"])
        assert find_surfaces(session, "PROJ-1") == []

    def test_uncached_tagged_key_is_skipped(self, session: Session) -> None:
        """Tag rows can outlive the cached Issue in rare cases (rename)."""
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo"])
        session.add(IssueTag(issue_key="GONE-999", tag="logo"))
        session.commit()

        assert find_surfaces(session, "PROJ-1") == []
