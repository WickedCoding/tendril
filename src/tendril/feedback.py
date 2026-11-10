"""Content-free feedback reports for the public GitHub repository.

The report is an allowlist: `FeedbackContext` holds every field that may leave
the machine, and nothing else. It never carries JIRA data, issue keys, URLs,
names, exception messages or absolute file paths. Tendril does not send the
report itself; it builds a prefilled "new issue" URL that the user reviews and
submits in their own browser, under their own GitHub account.

Adding a field here means it becomes public. `tests/test_feedback.py` pins the
field set so that change is always deliberate.
"""
from __future__ import annotations

import platform
import sysconfig
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from tendril import version_check
from tendril.config import DEFAULT_ROLLOVER_STATUSES, DEFAULT_SKILLS_TOTALS, Config

REPO_URL = "https://github.com/WickedCoding/tendril"
# Labels live in the templates: GitHub drops a `labels=` query parameter
# for anyone without triage rights, but applies template labels for everyone.
ISSUE_TEMPLATES: dict[str, str] = {"bug": "feedback-bug.md", "idea": "feedback-idea.md"}
MAX_FRAMES = 15
MAX_URL_LENGTH = 8000
PUBLIC_WARNING = (
    "This issue is public. Do not add issue keys, names, customer data or JIRA URLs."
)

Kind = Literal["bug", "idea"]


@dataclass(frozen=True)
class SanitizedError:
    """An exception reduced to its type and code locations. Never its message."""

    type_name: str
    frames: tuple[str, ...]


@dataclass(frozen=True)
class FeedbackContext:
    """Every field that may appear in a public feedback report."""

    tendril_version: str
    python_version: str
    os_name: str
    terminal_size: str
    screen_stack: tuple[str, ...]
    focused_widget: str | None
    recent_actions: tuple[str, ...]
    error: SanitizedError | None
    config_shape: tuple[tuple[str, bool], ...]


def environment() -> tuple[str, str, str]:
    """`(tendril_version, python_version, os_name)`."""
    try:
        tendril_version = version_check.installed_version()
    except Exception:  # noqa: BLE001 - a missing dist-info must not block a report
        tendril_version = "unknown"
    python_version = platform.python_version()
    os_name = f"{platform.system()} {platform.release()}".strip()
    return tendril_version, python_version, os_name


def config_shape(cfg: Config) -> tuple[tuple[str, bool], ...]:
    """Which optional config sections are set. Booleans only: no IDs, names or counts."""
    return (
        ("fields.feature_flags", bool(cfg.fields.feature_flags)),
        ("fields.sprint", bool(cfg.fields.sprint)),
        ("fields.story_points", bool(cfg.fields.story_points)),
        ("fields.skills", bool(cfg.fields.skills)),
        ("skills.totals customised", tuple(cfg.skills.totals) != DEFAULT_SKILLS_TOTALS),
        (
            "rollover.statuses customised",
            tuple(cfg.rollover.statuses) != DEFAULT_ROLLOVER_STATUSES,
        ),
        ("boards", bool(cfg.boards)),
    )


def _path_roots() -> list[tuple[Path, str]]:
    """Known roots, most specific first, with the prefix that replaces each one."""
    paths = sysconfig.get_paths()
    roots: list[tuple[Path, str]] = [(Path(__file__).resolve().parent, "tendril")]
    for key in ("purelib", "platlib"):
        roots.append((Path(paths[key]).resolve(), ""))
    roots.append((Path(paths["stdlib"]).resolve(), "<stdlib>"))
    return roots


def sanitize_path(filename: str) -> str:
    """Reduce a frame's filename to a path relative to a known root, or `<external>`."""
    if filename.startswith("<") and filename.endswith(">"):
        # Synthetic frames such as "<string>" carry no path.
        return filename
    try:
        resolved = Path(filename).resolve()
    except (OSError, ValueError):
        return "<external>"
    for root, prefix in _path_roots():
        if resolved.is_relative_to(root):
            rel = resolved.relative_to(root).as_posix()
            return f"{prefix}/{rel}" if prefix else rel
    return "<external>"


def sanitize_traceback(exc: BaseException) -> SanitizedError:
    """Type name plus the last `MAX_FRAMES` frames as `path:line in function`."""
    cls = type(exc)
    type_name = f"{cls.__module__}.{cls.__qualname__}"
    frames = traceback.extract_tb(exc.__traceback__)[-MAX_FRAMES:]
    return SanitizedError(
        type_name=type_name,
        frames=tuple(
            f"{sanitize_path(f.filename)}:{f.lineno} in {f.name}" for f in frames
        ),
    )


def render_context(ctx: FeedbackContext, kind: Kind | None = None) -> str:
    """The generated context block, exactly as it appears in the issue body.

    Config shape goes into bug reports only. With `kind=None` (the preview,
    before the user picks) it is shown and marked as such.
    """
    lines = [
        f"tendril: {ctx.tendril_version}",
        f"python: {ctx.python_version}",
        f"os: {ctx.os_name}",
        f"terminal: {ctx.terminal_size}",
        f"screens: {' > '.join(ctx.screen_stack) or '-'}",
        f"focused: {ctx.focused_widget or '-'}",
        "recent actions:",
    ]
    lines += [f"  - {a}" for a in ctx.recent_actions] or ["  -"]
    if kind != "idea":
        lines.append("config:" if kind == "bug" else "config (bug reports only):")
        lines += [f"  {name}: {'yes' if value else 'no'}" for name, value in ctx.config_shape]
    if ctx.error is None:
        lines.append("last error: -")
    else:
        lines.append(f"last error: {ctx.error.type_name}")
        lines += [f"  {frame}" for frame in ctx.error.frames]
    return "\n".join(lines)


def render_body(ctx: FeedbackContext, kind: Kind) -> str:
    return (
        f"> {PUBLIC_WARNING}\n\n"
        "## What happened\n\n\n"
        "## What you expected\n\n\n"
        "## Context (generated by tendril)\n\n"
        f"```\n{render_context(ctx, kind)}\n```\n"
    )


def _title(ctx: FeedbackContext, kind: Kind) -> str:
    where = ctx.screen_stack[-1] if ctx.screen_stack else "tendril"
    return f"[{kind}] {where}: "


def _build_url(ctx: FeedbackContext, kind: Kind) -> str:
    query = urlencode(
        {
            "template": ISSUE_TEMPLATES[kind],
            "title": _title(ctx, kind),
            "body": render_body(ctx, kind),
        }
    )
    return f"{REPO_URL}/issues/new?{query}"


def issue_url(ctx: FeedbackContext, kind: Kind) -> str:
    """Prefilled GitHub "new issue" URL. Drops error frames until it fits the URL limit."""
    url = _build_url(ctx, kind)
    while len(url) > MAX_URL_LENGTH and ctx.error is not None and ctx.error.frames:
        trimmed = SanitizedError(ctx.error.type_name, ctx.error.frames[1:])
        ctx = replace(ctx, error=trimmed)
        url = _build_url(ctx, kind)
    return url


__all__ = [
    "FeedbackContext",
    "Kind",
    "PUBLIC_WARNING",
    "REPO_URL",
    "SanitizedError",
    "config_shape",
    "environment",
    "issue_url",
    "render_body",
    "render_context",
    "sanitize_path",
    "sanitize_traceback",
]
