from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tendril.alerts import ops
from tendril.alerts.matcher import find_surfaces
from tendril.db.models import Issue, IssueTag


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


class TestAlertOps:
    def test_mark_is_idempotent(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        first = ops.mark_alert(session, "PROJ-1")
        second = ops.mark_alert(session, "PROJ-1")
        assert first.issue_key == second.issue_key == "PROJ-1"
        assert len(ops.list_alerts(session)) == 1

    def test_unmark_reports_deletion(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        ops.mark_alert(session, "PROJ-1")
        assert ops.unmark_alert(session, "PROJ-1") is True
        assert ops.unmark_alert(session, "PROJ-1") is False

    def test_is_alert(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        assert ops.is_alert(session, "PROJ-1") is False
        ops.mark_alert(session, "PROJ-1")
        assert ops.is_alert(session, "PROJ-1") is True


class TestFindSurfaces:
    def test_returns_empty_when_viewed_has_no_tags(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-2", "logo blocker")
        ops.add_tags(session, "PROJ-2", ["logo"])
        ops.mark_alert(session, "PROJ-2")
        assert find_surfaces(session, "PROJ-1") == []

    def test_surfaces_alert_with_shared_tag(self, session: Session) -> None:
        _issue(session, "PROJ-1", "logo blocker")
        _issue(session, "PROJ-2", "add logo to layout")
        ops.add_tags(session, "PROJ-1", ["logo", "branding"])
        ops.add_tags(session, "PROJ-2", ["logo", "deal-placement"])
        ops.mark_alert(session, "PROJ-1")

        surfaces = find_surfaces(session, "PROJ-2")
        assert len(surfaces) == 1
        surfaced_issue, shared_tags = surfaces[0]
        assert surfaced_issue.key == "PROJ-1"
        assert shared_tags == ["logo"]

    def test_never_surfaces_self(self, session: Session) -> None:
        _issue(session, "PROJ-1", "logo blocker")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.mark_alert(session, "PROJ-1")
        # Viewing an issue with a shared tag but that IS the alert-owner: excluded.
        _issue(session, "PROJ-2", "unrelated")
        ops.add_tags(session, "PROJ-2", ["logo"])
        # PROJ-1 is the alert, viewing PROJ-1 must not surface itself.
        assert find_surfaces(session, "PROJ-1") == []

    def test_alert_without_tags_never_fires(self, session: Session) -> None:
        _issue(session, "PROJ-1", "no tags")
        ops.mark_alert(session, "PROJ-1")
        _issue(session, "PROJ-2")
        ops.add_tags(session, "PROJ-2", ["logo"])
        assert find_surfaces(session, "PROJ-2") == []

    def test_non_alert_issues_do_not_surface(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-2")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.add_tags(session, "PROJ-2", ["logo"])
        # No alert marker anywhere.
        assert find_surfaces(session, "PROJ-2") == []

    def test_multiple_shared_tags_are_all_reported(self, session: Session) -> None:
        _issue(session, "PROJ-1", "logo + branding blocker")
        _issue(session, "PROJ-2", "logo + branding")
        ops.add_tags(session, "PROJ-1", ["logo", "branding", "carousel"])
        ops.add_tags(session, "PROJ-2", ["logo", "branding", "deal-placement"])
        ops.mark_alert(session, "PROJ-1")

        surfaces = find_surfaces(session, "PROJ-2")
        assert len(surfaces) == 1
        _, shared_tags = surfaces[0]
        assert sorted(shared_tags) == ["branding", "logo"]

    def test_orders_multiple_surfaces_by_issue_key(self, session: Session) -> None:
        _issue(session, "PROJ-1")
        _issue(session, "PROJ-10", "later alert")
        _issue(session, "PROJ-2", "earlier alert")
        ops.add_tags(session, "PROJ-1", ["logo"])
        ops.add_tags(session, "PROJ-2", ["logo"])
        ops.add_tags(session, "PROJ-10", ["logo"])
        ops.mark_alert(session, "PROJ-2")
        ops.mark_alert(session, "PROJ-10")

        surfaces = find_surfaces(session, "PROJ-1")
        keys = [i.key for i, _ in surfaces]
        assert keys == ["PROJ-10", "PROJ-2"]

    def test_alert_owner_not_yet_cached_is_skipped(self, session: Session) -> None:
        """Rows in issue_alert / issue_tag can outlive the cached Issue in rare cases (rename)."""
        _issue(session, "PROJ-1")
        ops.add_tags(session, "PROJ-1", ["logo"])
        # Directly insert tag + alert for a key with no matching Issue row.
        session.add(IssueTag(issue_key="GONE-999", tag="logo"))
        ops.mark_alert(session, "GONE-999")
        session.commit()

        assert find_surfaces(session, "PROJ-1") == []
