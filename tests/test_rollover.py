from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tendril.config import (
    BoardConfig,
    Config,
    FieldsConfig,
    JiraConfig,
    RolloverConfig,
    SkillsConfig,
)
from tendril.db.models import (
    Issue,
    IssueSprint,
    ROLLOVER_STEP_CLOSE,
    ROLLOVER_STEP_MOVE,
    ROLLOVER_STEP_RANK,
    ROLLOVER_STEP_START,
    RolloverAttempt,
    RolloverLog,
    Sprint,
)
from tendril.operations import ops
from tendril.sync.rollover import (
    carryover_totals,
    compute_totals,
    increment_sprint_name,
    resolve_target_sprint,
)


# ---------- pure resolution ----------


class TestIncrementSprintName:
    def test_plain_trailing_number(self) -> None:
        assert increment_sprint_name("Sprint 17") == "Sprint 18"

    def test_preserves_zero_padding(self) -> None:
        assert increment_sprint_name("Sprint 09") == "Sprint 10"
        assert increment_sprint_name("S001") == "S002"

    def test_widens_when_number_overflows_width(self) -> None:
        assert increment_sprint_name("S99") == "S100"

    def test_returns_none_on_unmatched(self) -> None:
        assert increment_sprint_name("just letters") is None

    def test_custom_pattern(self) -> None:
        got = increment_sprint_name(
            "MM-42",
            pattern=r"^(?P<prefix>MM-)(?P<number>\d+)$",
        )
        assert got == "MM-43"


def _cfg(**overrides) -> Config:
    base = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        fields=FieldsConfig(sprint="cf_10020", story_points="cf_10032"),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _issue(
    session: Session,
    key: str,
    *,
    status: str = "To Do",
    sp: float | None = None,
    skills: list[str] | None = None,
) -> Issue:
    row = Issue(
        key=key, summary=f"{key} summary", status=status, issuetype="Task",
        story_points=sp, skills=skills or [],
        raw_json={}, last_synced_at=_now(),
    )
    session.add(row)
    return row


def _sprint(session: Session, sid: int, name: str, state: str, board_id: int = 1) -> Sprint:
    row = Sprint(id=sid, name=name, state=state, board_id=board_id)
    session.add(row)
    return row


# ---------- target resolution against the cache ----------


def test_resolve_target_sprint_finds_next_by_name(session: Session) -> None:
    _sprint(session, 100, "Sprint 17", "active", board_id=5)
    _sprint(session, 101, "Sprint 18", "future", board_id=5)
    _issue(session, "MMINT-1")
    session.add(IssueSprint(issue_key="MMINT-1", sprint_id=100))
    session.commit()

    cfg = _cfg()
    resolution = resolve_target_sprint(session, cfg, session.get(Sprint, 100))
    assert resolution.predicted_name == "Sprint 18"
    assert resolution.target is not None
    assert resolution.target.id == 101
    assert resolution.reason is None


def test_resolve_target_sprint_reports_missing(session: Session) -> None:
    _sprint(session, 100, "Sprint 17", "active", board_id=5)
    session.commit()

    cfg = _cfg()
    resolution = resolve_target_sprint(session, cfg, session.get(Sprint, 100))
    assert resolution.predicted_name == "Sprint 18"
    assert resolution.target is None
    assert "Sprint 18" in (resolution.reason or "")


def test_resolve_uses_per_project_pattern(session: Session) -> None:
    _sprint(session, 100, "MMINT-42", "active", board_id=7)
    _sprint(session, 101, "MMINT-43", "future", board_id=7)
    _issue(session, "MMINT-1")
    session.add(IssueSprint(issue_key="MMINT-1", sprint_id=100))
    session.commit()

    cfg = _cfg(
        boards={
            "MMINT": BoardConfig(
                sprint_pattern=r"^(?P<prefix>MMINT-)(?P<number>\d+)$",
            ),
        },
    )
    resolution = resolve_target_sprint(session, cfg, session.get(Sprint, 100))
    assert resolution.target is not None
    assert resolution.target.id == 101


# ---------- totals ----------


class TestTotals:
    def test_bucket_by_status(self, session: Session) -> None:
        a = _issue(session, "A-1", status="To Do", sp=3)
        b = _issue(session, "A-2", status="In Progress", sp=5)
        c = _issue(session, "A-3", status="Closed", sp=8)
        totals = compute_totals([a, b, c], ["Backend"])
        assert totals.to_do == 3
        assert totals.in_progress == 5
        assert totals.other == 8
        assert totals.total == 16

    def test_none_sp_counts_as_zero(self, session: Session) -> None:
        a = _issue(session, "A-1", status="To Do", sp=None)
        totals = compute_totals([a], [])
        assert totals.total == 0

    def test_per_skill_duplicates_across_skills(self, session: Session) -> None:
        """One 8-SP issue in ['Backend', 'Frontend'] contributes 8 to BOTH totals."""
        row = _issue(session, "A-1", status="To Do", sp=8, skills=["Backend", "Frontend"])
        totals = compute_totals([row], ["Backend", "Frontend"])
        assert totals.per_skill == {"Backend": 8, "Frontend": 8}

    def test_per_skill_matches_case_insensitively(self, session: Session) -> None:
        row = _issue(session, "A-1", status="To Do", sp=3, skills=["backend"])
        totals = compute_totals([row], ["Backend"])
        assert totals.per_skill["Backend"] == 3


class TestCarryover:
    def test_reduction_shaves_effective_sp(self, session: Session) -> None:
        base_issue = _issue(session, "B-1", status="To Do", sp=5, skills=["Backend"])
        session.flush()
        base = compute_totals([base_issue], ["Backend"])
        # A carried issue with SP=8, reduction=3 → 5 effective
        carried = _issue(session, "C-1", status="To Do", sp=8, skills=["Backend"])
        projected = carryover_totals(
            base, [carried], {"C-1": 3.0}, ["Backend"],
        )
        assert projected.to_do == 5 + 5
        assert projected.per_skill["Backend"] == 5 + 5

    def test_reduction_larger_than_sp_clamps_to_zero(self, session: Session) -> None:
        base = compute_totals([], ["Backend"])
        carried = _issue(session, "C-1", status="To Do", sp=2, skills=["Backend"])
        projected = carryover_totals(base, [carried], {"C-1": 99}, ["Backend"])
        assert projected.to_do == 0


# ---------- execute_rollover: happy path ----------


class RolloverFakeJira:
    """Recording fake for rollover tests: refetches return the cached fixture.

    `sprint_updates_that_raise` lets tests inject a failure at a specific step.
    """

    def __init__(
        self,
        issues: dict[str, dict],
        *,
        sprint_updates_that_raise: dict[int, Exception] | None = None,
        raise_on_rank: Exception | None = None,
    ) -> None:
        self._issues = issues
        self.sprint_moves: list[tuple[int, list[str]]] = []
        self.sprint_updates: list[tuple[int, dict]] = []
        self.rank_calls: list[dict] = []
        self._raise_on = sprint_updates_that_raise or {}
        self._raise_on_rank = raise_on_rank

    def issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict:
        return self._issues[key]

    def enhanced_jql(self, *a, **kw):  # pragma: no cover — not used in these tests
        raise AssertionError("execute_rollover should not paginate")

    def add_issues_to_sprint(self, sprint_id: int, issues: list[str]) -> dict:
        self.sprint_moves.append((sprint_id, list(issues)))
        return {}

    def update_partially_sprint(self, sprint_id: int, data: dict) -> dict:
        self.sprint_updates.append((sprint_id, dict(data)))
        exc = self._raise_on.get(sprint_id)
        if exc is not None:
            raise exc
        return {}

    def rank_issues(self, data: dict) -> dict:
        self.rank_calls.append(dict(data))
        if self._raise_on_rank is not None:
            raise self._raise_on_rank
        return {}


def _payload(key: str, sprint_id: int) -> dict:
    """Minimal issue payload that speaks the sprint customfield."""
    return {
        "key": key,
        "fields": {
            "summary": f"{key} summary",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Task"},
            "cf_10020": [{"id": sprint_id, "name": f"S{sprint_id}", "state": "future"}],
            "cf_10032": 5,
        },
    }


def _seed_two_sprints(session: Session) -> None:
    _sprint(session, 100, "Sprint 17", "active", board_id=1)
    _sprint(session, 101, "Sprint 18", "future", board_id=1)
    _issue(session, "MMINT-1", status="In Progress", sp=5)
    _issue(session, "MMINT-2", status="To Do", sp=3)
    session.add(IssueSprint(issue_key="MMINT-1", sprint_id=100))
    session.add(IssueSprint(issue_key="MMINT-2", sprint_id=100))
    session.commit()


def test_execute_rollover_happy_path(session: Session) -> None:
    _seed_two_sprints(session)
    client = RolloverFakeJira({
        "MMINT-1": _payload("MMINT-1", 101),
        "MMINT-2": _payload("MMINT-2", 101),
    })
    cfg = _cfg()
    ops.start_rollover(
        session,
        source_sprint_id=100,
        target_sprint_id=101,
        selected_keys=["MMINT-1", "MMINT-2"],
        target_order_keys=["MMINT-1", "MMINT-2"],
    )
    log = ops.execute_rollover(
        client, session,
        source_sprint_id=100,
        source_sprint_name="Sprint 17",
        target_sprint_name="Sprint 18",
        cfg=cfg,
    )

    # Client calls in the right order: move, rank, close, start.
    assert client.sprint_moves == [(101, ["MMINT-1", "MMINT-2"])]
    assert client.rank_calls == [
        {"issues": ["MMINT-2"], "rankAfterIssue": "MMINT-1"},
    ]
    assert client.sprint_updates == [
        (100, {"state": "closed"}),
        (101, {"state": "active"}),
    ]

    # Local cache reflects the new sprint states.
    assert session.get(Sprint, 100).state == "closed"
    assert session.get(Sprint, 101).state == "active"

    # Attempt cleared; success logged.
    assert session.get(RolloverAttempt, 100) is None
    assert log.source_sprint_name == "Sprint 17"
    assert log.target_sprint_name == "Sprint 18"
    assert log.moved_issue_keys == ["MMINT-1", "MMINT-2"]


def test_execute_rollover_requires_prior_start(session: Session) -> None:
    _seed_two_sprints(session)
    client = RolloverFakeJira({})
    with pytest.raises(ValueError, match="No RolloverAttempt"):
        ops.execute_rollover(
            client, session,
            source_sprint_id=100,
            source_sprint_name="Sprint 17",
            target_sprint_name="Sprint 18",
        )


def test_start_rollover_refreshes_existing_attempt(session: Session) -> None:
    """A resume flow may revise the selection — new keys land, moved_issue_keys survive."""
    _seed_two_sprints(session)
    now = _now()
    session.add(RolloverAttempt(
        source_sprint_id=100, target_sprint_id=101,
        selected_issue_keys=["MMINT-1"], moved_issue_keys=["MMINT-1"],
        completed_step=ROLLOVER_STEP_MOVE,
        error="prior failure",
        created_at=now, updated_at=now,
    ))
    session.commit()

    ops.start_rollover(
        session,
        source_sprint_id=100,
        target_sprint_id=101,
        selected_keys=["MMINT-1", "MMINT-2"],
        target_order_keys=["MMINT-2", "MMINT-1"],
    )
    attempt = session.get(RolloverAttempt, 100)
    assert attempt is not None
    assert attempt.selected_issue_keys == ["MMINT-1", "MMINT-2"]
    # A resume refreshes the target order too — user may have reordered.
    assert attempt.target_order_keys == ["MMINT-2", "MMINT-1"]
    # moved_issue_keys and completed_step are preserved so the resume can skip past
    # already-succeeded steps.
    assert attempt.moved_issue_keys == ["MMINT-1"]
    assert attempt.completed_step == ROLLOVER_STEP_MOVE
    # Prior error cleared so a fresh error can land.
    assert attempt.error is None


def test_execute_rollover_records_error_and_preserves_attempt(session: Session) -> None:
    _seed_two_sprints(session)
    client = RolloverFakeJira(
        {
            "MMINT-1": _payload("MMINT-1", 101),
            "MMINT-2": _payload("MMINT-2", 101),
        },
        sprint_updates_that_raise={100: RuntimeError("JIRA rejected close")},
    )
    cfg = _cfg()
    ops.start_rollover(
        session,
        source_sprint_id=100, target_sprint_id=101,
        selected_keys=["MMINT-1", "MMINT-2"],
        target_order_keys=["MMINT-1", "MMINT-2"],
    )

    with pytest.raises(RuntimeError, match="JIRA rejected close"):
        ops.execute_rollover(
            client, session,
            source_sprint_id=100,
            source_sprint_name="Sprint 17",
            target_sprint_name="Sprint 18",
            cfg=cfg,
        )

    attempt = session.get(RolloverAttempt, 100)
    assert attempt is not None, "attempt must survive the failure so resume is possible"
    # Move + rank succeeded, close was the step that raised — so the last
    # completed step recorded is rank.
    assert attempt.completed_step == ROLLOVER_STEP_RANK
    assert attempt.error == "JIRA rejected close"
    assert session.query(RolloverLog).count() == 0


def test_execute_rollover_resumes_past_completed_steps(session: Session) -> None:
    _seed_two_sprints(session)
    now = _now()
    # Attempt already has the move + close done — only start_target + log remain.
    session.add(RolloverAttempt(
        source_sprint_id=100, target_sprint_id=101,
        selected_issue_keys=["MMINT-1"],
        moved_issue_keys=["MMINT-1"],
        completed_step=ROLLOVER_STEP_CLOSE,
        error=None,
        created_at=now, updated_at=now,
    ))
    session.commit()

    client = RolloverFakeJira({"MMINT-1": _payload("MMINT-1", 101)})
    ops.execute_rollover(
        client, session,
        source_sprint_id=100,
        source_sprint_name="Sprint 17",
        target_sprint_name="Sprint 18",
    )

    # No re-move, no re-close — only the start.
    assert client.sprint_moves == []
    assert client.sprint_updates == [(101, {"state": "active"})]
    assert session.get(RolloverAttempt, 100) is None
    assert session.query(RolloverLog).count() == 1


def test_execute_rollover_with_empty_selection_still_advances_sprints(
    session: Session,
) -> None:
    """A selection-free rollover is legal — close source, start target, log."""
    _seed_two_sprints(session)
    client = RolloverFakeJira({})
    ops.start_rollover(
        session,
        source_sprint_id=100, target_sprint_id=101,
        selected_keys=[],
        target_order_keys=[],
    )
    ops.execute_rollover(
        client, session,
        source_sprint_id=100,
        source_sprint_name="Sprint 17",
        target_sprint_name="Sprint 18",
    )
    assert client.sprint_moves == []
    # Empty target order means nothing to rank — the endpoint isn't hit.
    assert client.rank_calls == []
    assert client.sprint_updates == [
        (100, {"state": "closed"}),
        (101, {"state": "active"}),
    ]


def test_rank_issues_in_order_chunks_at_fifty(session: Session) -> None:
    """`rank_issues_in_order` splits >50 keys into chained rank-after calls."""
    from tendril.jira.write import rank_issues_in_order

    keys = [f"K-{i}" for i in range(120)]
    client = RolloverFakeJira({})
    rank_issues_in_order(client, keys)

    # 120 keys: anchor K-0, then chunks of 49 (K-1..K-49), 49 (K-50..K-98),
    # 21 (K-99..K-119) — each anchored on the previous chunk's last key.
    assert [c["rankAfterIssue"] for c in client.rank_calls] == [
        "K-0", "K-49", "K-98",
    ]
    assert client.rank_calls[0]["issues"][0] == "K-1"
    assert client.rank_calls[0]["issues"][-1] == "K-49"
    assert client.rank_calls[-1]["issues"][-1] == "K-119"
    # Every key except the anchor appears exactly once across all chunks.
    seen = [k for c in client.rank_calls for k in c["issues"]]
    assert seen == keys[1:]


def test_execute_rollover_resume_skips_completed_rank(session: Session) -> None:
    """A resume that already has rank done must not re-rank."""
    _seed_two_sprints(session)
    now = _now()
    session.add(RolloverAttempt(
        source_sprint_id=100, target_sprint_id=101,
        selected_issue_keys=["MMINT-1"],
        moved_issue_keys=["MMINT-1"],
        target_order_keys=["MMINT-1", "MMINT-2"],
        completed_step=ROLLOVER_STEP_RANK,
        error=None,
        created_at=now, updated_at=now,
    ))
    session.commit()

    client = RolloverFakeJira({"MMINT-1": _payload("MMINT-1", 101)})
    ops.execute_rollover(
        client, session,
        source_sprint_id=100,
        source_sprint_name="Sprint 17",
        target_sprint_name="Sprint 18",
    )

    # Rank already done — no rank call, no re-move; close and start both fire.
    assert client.sprint_moves == []
    assert client.rank_calls == []
    assert client.sprint_updates == [
        (100, {"state": "closed"}),
        (101, {"state": "active"}),
    ]
