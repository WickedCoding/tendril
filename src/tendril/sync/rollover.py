"""Sprint rollover resolution.

Everything read-only and cache-local: predicts the next sprint's name from the
current one, then looks up the matching Sprint row. Actual write operations
(move issues, close, start) live in operations/ops.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from tendril.config import Config, DEFAULT_SPRINT_PATTERN
from tendril.db.models import Issue, IssueSprint, Sprint


@dataclass(frozen=True)
class TargetResolution:
    """Outcome of resolving the next sprint for a source sprint.

    Exactly one of `target` / `reason` is set:
      - target set → next sprint exists in the cache and can be used
      - reason set → next sprint could not be resolved; the string is user-facing
    """

    predicted_name: str | None
    target: Sprint | None
    reason: str | None


def increment_sprint_name(name: str, pattern: str = DEFAULT_SPRINT_PATTERN) -> str | None:
    """Predict the next sprint name from `name` using `pattern`.

    The regex must define named groups `prefix` and `number` (validated at
    config load). Zero-padding is preserved: `"Sprint 09"` → `"Sprint 10"`,
    `"S001"` → `"S002"`, `"S99"` → `"S100"`. Returns None when the pattern
    doesn't match — the caller decides how to report it.
    """
    m = re.match(pattern, name)
    if m is None:
        return None
    prefix = m.group("prefix")
    number = m.group("number")
    incremented = str(int(number) + 1)
    padded = incremented.zfill(len(number))
    return f"{prefix}{padded}"


def _project_key_for_sprint(session: Session, sprint_id: int) -> str | None:
    """Peek at any issue in the sprint to derive its project key.

    Sprints don't carry a project reference in JIRA's model, so we lean on the
    issues that live in them. An empty sprint yields None — the caller must
    fall back to the default pattern.
    """
    stmt = (
        select(Issue.key)
        .join(IssueSprint, IssueSprint.issue_key == Issue.key)
        .where(IssueSprint.sprint_id == sprint_id)
        .limit(1)
    )
    key = session.execute(stmt).scalar_one_or_none()
    if not key or "-" not in key:
        return None
    return key.split("-", 1)[0]


def sprint_pattern_for(cfg: Config, project_key: str | None) -> str:
    """Return the sprint-name regex configured for `project_key`, else the default."""
    if project_key and project_key in cfg.boards:
        return cfg.boards[project_key].sprint_pattern
    return DEFAULT_SPRINT_PATTERN


def resolve_target_sprint(
    session: Session,
    cfg: Config,
    source: Sprint,
) -> TargetResolution:
    """Find the sprint that would follow `source`, using cache-local data.

    Match rules: same `board_id` (when the source has one) and the predicted
    name. When either lookup fails, `reason` explains what the user must do.
    """
    project_key = _project_key_for_sprint(session, source.id)
    pattern = sprint_pattern_for(cfg, project_key)
    predicted = increment_sprint_name(source.name, pattern)
    if predicted is None:
        return TargetResolution(
            predicted_name=None,
            target=None,
            reason=(
                f"Could not predict next sprint name from {source.name!r} "
                f"using pattern {pattern!r}. Adjust [boards.<PROJECT>].sprint_pattern "
                "in your config."
            ),
        )

    stmt = select(Sprint).where(Sprint.name == predicted)
    if source.board_id is not None:
        stmt = stmt.where(Sprint.board_id == source.board_id)
    target = session.execute(stmt).scalar_one_or_none()
    if target is None:
        return TargetResolution(
            predicted_name=predicted,
            target=None,
            reason=(
                f"No cached sprint named {predicted!r} on this board. "
                "Create it in JIRA first, then sync. Tendril never creates sprints."
            ),
        )
    return TargetResolution(predicted_name=predicted, target=target, reason=None)


def list_active_sprints(session: Session) -> list[Sprint]:
    """Every cached sprint in the `active` state, ordered by name (stable for pickers)."""
    stmt = select(Sprint).where(Sprint.state == "active").order_by(Sprint.name)
    return list(session.scalars(stmt).all())


def source_sprint_issues(session: Session, sprint_id: int) -> list[Issue]:
    """All cached issues that belong to `sprint_id`, ordered by key for a stable layout."""
    stmt = (
        select(Issue)
        .join(IssueSprint, IssueSprint.issue_key == Issue.key)
        .where(IssueSprint.sprint_id == sprint_id)
        .order_by(Issue.key)
    )
    return list(session.scalars(stmt).all())


@dataclass(frozen=True)
class SprintTotals:
    """Story-point totals for a sprint, split by the two statuses the right panel cares about.

    Any status not in the "to-do family" or "in-progress family" is folded into
    `other`. Per-skill totals sum an issue's SP into every one of the tracked
    skills the issue carries — the same issue with `["Backend", "Frontend"]`
    contributes fully to both totals, matching the ratified duplicate-per-skill decision.
    """

    to_do: float
    in_progress: float
    other: float
    per_skill: dict[str, float]

    @property
    def total(self) -> float:
        return self.to_do + self.in_progress + self.other


_TO_DO_STATUSES: frozenset[str] = frozenset({"To Do", "Open", "Backlog"})
_IN_PROGRESS_STATUSES: frozenset[str] = frozenset({
    "In Progress", "Code Review", "Functional Review",
})


def _bucket(status: str | None) -> str:
    if status in _TO_DO_STATUSES:
        return "to_do"
    if status in _IN_PROGRESS_STATUSES:
        return "in_progress"
    return "other"


def compute_totals(
    issues: list[Issue],
    tracked_skills: list[str],
) -> SprintTotals:
    """Aggregate SP across `issues`, split by status bucket and per tracked skill.

    Issues with `story_points is None` contribute zero (no synthetic default).
    `tracked_skills` matches skill labels case-insensitively so a config of
    `["Backend"]` still counts `"backend"` on legacy tenants.
    """
    to_do = 0.0
    in_progress = 0.0
    other = 0.0
    per_skill: dict[str, float] = {s: 0.0 for s in tracked_skills}
    lower_tracked = {s.lower(): s for s in tracked_skills}
    for issue in issues:
        sp = float(issue.story_points or 0)
        bucket = _bucket(issue.status)
        if bucket == "to_do":
            to_do += sp
        elif bucket == "in_progress":
            in_progress += sp
        else:
            other += sp
        for skill in issue.skills or []:
            canonical = lower_tracked.get(str(skill).lower())
            if canonical is not None:
                per_skill[canonical] += sp
    return SprintTotals(
        to_do=to_do,
        in_progress=in_progress,
        other=other,
        per_skill=per_skill,
    )


def carryover_totals(
    base: SprintTotals,
    carried_issues: list[Issue],
    reductions: dict[str, float],
    tracked_skills: list[str],
) -> SprintTotals:
    """Base target totals + remaining-SP contribution from each carried issue.

    `reductions` maps issue key → the SP the user wants to shave off before the
    carry; the effective carried SP is `max(0, story_points - reduction)`. No
    JIRA write happens here — this only shapes the projected right-panel totals.
    """
    projected_to_do = base.to_do
    projected_in_progress = base.in_progress
    projected_other = base.other
    per_skill = dict(base.per_skill)
    lower_tracked = {s.lower(): s for s in tracked_skills}
    for issue in carried_issues:
        original = float(issue.story_points or 0)
        reduction = float(reductions.get(issue.key, 0) or 0)
        carried = max(0.0, original - reduction)
        bucket = _bucket(issue.status)
        if bucket == "to_do":
            projected_to_do += carried
        elif bucket == "in_progress":
            projected_in_progress += carried
        else:
            projected_other += carried
        for skill in issue.skills or []:
            canonical = lower_tracked.get(str(skill).lower())
            if canonical is not None:
                per_skill[canonical] = per_skill.get(canonical, 0.0) + carried
    return SprintTotals(
        to_do=projected_to_do,
        in_progress=projected_in_progress,
        other=projected_other,
        per_skill=per_skill,
    )
