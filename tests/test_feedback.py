from __future__ import annotations

import inspect
import sysconfig
from dataclasses import fields
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

import tendril
from tendril import feedback
from tendril.config import Config, FieldsConfig, JiraConfig
from tendril.db.engine import build_engine, session_factory
from tendril.db.schema import init_schema
from tendril.jira.dto import normalize_issue
from tendril.sync.commands import add_to_watchlist
from tendril.sync.pipeline import upsert_issue
from tendril.tui.app import TendrilApp

SECRET_URL = "https://secret-corp.atlassian.net"
SECRET_EMAIL = "person@secret-corp.nl"
SECRET_FIELD = "customfield_99999"


def _ctx(**overrides) -> feedback.FeedbackContext:
    base = dict(
        tendril_version="1.7.1",
        python_version="3.12.0",
        os_name="Darwin 27",
        terminal_size="120x40",
        screen_stack=("WatchlistScreen",),
        focused_widget="DataTable",
        recent_actions=(),
        error=None,
        config_shape=feedback.config_shape(Config(jira=JiraConfig(url="https://x", email="me@x"))),
    )
    base.update(overrides)
    return feedback.FeedbackContext(**base)


# ---- allowlist ------------------------------------------------------------


def test_allowlist_is_pinned() -> None:
    """Every field here becomes public. Change this set only on purpose."""
    assert {f.name for f in fields(feedback.FeedbackContext)} == {
        "tendril_version",
        "python_version",
        "os_name",
        "terminal_size",
        "screen_stack",
        "focused_widget",
        "recent_actions",
        "error",
        "config_shape",
    }
    assert {f.name for f in fields(feedback.SanitizedError)} == {"type_name", "frames"}


def test_config_shape_is_booleans_only() -> None:
    cfg = Config(
        jira=JiraConfig(url=SECRET_URL, email=SECRET_EMAIL),
        fields=FieldsConfig(sprint=SECRET_FIELD),
    )
    shape = dict(feedback.config_shape(cfg))
    assert all(isinstance(v, bool) for v in shape.values())
    assert shape["fields.sprint"] is True
    assert shape["fields.feature_flags"] is False
    # Defaults are not "customised".
    assert shape["skills.totals customised"] is False
    assert shape["rollover.statuses customised"] is False


# ---- traceback sanitizing -------------------------------------------------


def test_sanitize_path_maps_known_roots() -> None:
    pkg = Path(tendril.__file__).resolve().parent
    assert feedback.sanitize_path(str(pkg / "tui" / "app.py")) == "tendril/tui/app.py"

    purelib = Path(sysconfig.get_paths()["purelib"])
    assert feedback.sanitize_path(str(purelib / "textual" / "app.py")) == "textual/app.py"

    stdlib = Path(sysconfig.get_paths()["stdlib"])
    assert feedback.sanitize_path(str(stdlib / "json" / "decoder.py")) == "<stdlib>/json/decoder.py"

    assert feedback.sanitize_path("/Users/someone/private/thing.py") == "<external>"
    assert feedback.sanitize_path("<string>") == "<string>"


def _raise_with_secret() -> None:
    raise RuntimeError(f"PROJ-1 leaked {SECRET_URL} {SECRET_EMAIL}")


def test_sanitize_traceback_drops_message_and_paths() -> None:
    with pytest.raises(RuntimeError) as info:
        _raise_with_secret()
    err = feedback.sanitize_traceback(info.value)
    assert err.type_name == "builtins.RuntimeError"
    text = "\n".join(err.frames)
    assert "_raise_with_secret" in text
    assert "PROJ-1" not in text
    assert "secret-corp" not in text
    # This test file sits outside every known root.
    assert all(frame.startswith("<external>:") for frame in err.frames)


def test_url_stays_under_limit_with_deep_traceback() -> None:
    long_frames = tuple(f"tendril/{'x' * 200}.py:{i} in fn" for i in range(100))
    ctx = _ctx(error=feedback.SanitizedError("builtins.RecursionError", long_frames))
    url = feedback.issue_url(ctx, "bug")
    assert len(url) <= feedback.MAX_URL_LENGTH
    assert "RecursionError" in unquote_plus(url)


def test_config_only_in_bug_reports() -> None:
    ctx = _ctx()
    bug = unquote_plus(feedback.issue_url(ctx, "bug"))
    idea = unquote_plus(feedback.issue_url(ctx, "idea"))
    assert "fields.sprint" in bug and "config:" in bug
    assert "fields.sprint" not in idea and "config" not in idea
    preview = feedback.render_context(ctx)
    assert "config (bug reports only):" in preview


def test_issue_url_shape() -> None:
    url = feedback.issue_url(_ctx(screen_stack=("WatchlistScreen", "IssueDetailScreen")), "idea")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{feedback.REPO_URL}/issues/new"
    query = parse_qs(parsed.query)
    assert query["title"] == ["[idea] IssueDetailScreen: "]
    assert "labels" not in query  # GitHub drops it for users without triage rights
    assert query["template"] == ["feedback-idea.md"]
    bug_query = parse_qs(urlparse(feedback.issue_url(_ctx(), "bug")).query)
    assert bug_query["template"] == ["feedback-bug.md"]
    assert feedback.PUBLIC_WARNING in query["body"][0]


def test_issue_templates_exist_with_existing_labels() -> None:
    repo = Path(tendril.__file__).resolve().parents[2]
    expected = {"feedback-bug.md": "labels: bug", "feedback-idea.md": "labels: enhancement"}
    assert set(feedback.ISSUE_TEMPLATES.values()) == set(expected)
    for name, label_line in expected.items():
        text = (repo / ".github" / "ISSUE_TEMPLATE" / name).read_text()
        assert label_line in text.splitlines()


# ---- entry point: command palette only ------------------------------------


def test_feedback_has_no_binding_and_no_action() -> None:
    import tendril.tui.screens as screens_pkg
    from textual.binding import Binding

    assert not hasattr(TendrilApp, "action_open_feedback")
    sources = [inspect.getsource(TendrilApp)]
    for path in Path(screens_pkg.__file__).parent.glob("*.py"):
        if path.name != "feedback_modal.py":
            sources.append(path.read_text())
    for src in sources:
        for line in src.splitlines():
            if "Binding(" in line:
                assert "feedback" not in line.lower(), line
    for binding in TendrilApp.BINDINGS:
        action = binding.action if isinstance(binding, Binding) else binding[1]
        assert "feedback" not in action


# ---- end-to-end: palette → modal → URL, with nothing leaking ---------------


def _seed(load_fixture) -> str:
    engine = build_engine()
    init_schema(engine)
    raw = load_fixture("issue_sample.json")
    with session_factory(engine)() as session:
        upsert_issue(session, normalize_issue(raw))
        add_to_watchlist(session, ["PROJ-1"])
    return raw["fields"]["summary"]


def _cursor_to_key(table, key: str) -> None:
    for i, k in enumerate(table.rows.keys()):
        if str(k.value) == key:
            table.move_cursor(row=i)
            return
    raise AssertionError(f"row {key} not found in table")


async def test_palette_feedback_flow_leaks_nothing(
    isolated_xdg: Path, load_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _seed(load_fixture)
    cfg = Config(
        jira=JiraConfig(url=SECRET_URL, email=SECRET_EMAIL),
        fields=FieldsConfig(sprint=SECRET_FIELD),
    )
    app = TendrilApp(cfg)
    opened: list[str] = []
    monkeypatch.setattr(app, "open_url", lambda url, **_: opened.append(url))

    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import DataTable

        _cursor_to_key(app.screen.query_one(DataTable), "PROJ-1")
        await pilot.press("enter")
        await pilot.pause()
        from tendril.tui.screens.issue_detail import IssueDetailScreen

        assert isinstance(app.screen, IssueDetailScreen)

        try:
            _raise_with_secret()
        except RuntimeError as e:
            app.record_error(e)

        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press(*"feedback")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause()

        from tendril.tui.screens.feedback_modal import FeedbackModal

        assert isinstance(app.screen, FeedbackModal)
        ctx = app.screen._ctx
        assert ctx.screen_stack[-1] == "IssueDetailScreen"
        assert "CommandPalette" not in ctx.screen_stack
        assert ctx.recent_actions == ("open WatchlistScreen", "open IssueDetailScreen")

        await pilot.press("b")
        await pilot.pause()

    assert len(opened) == 1
    url = opened[0]
    assert url.startswith(f"{feedback.REPO_URL}/issues/new?")
    decoded = unquote_plus(url)
    assert "builtins.RuntimeError" in decoded
    assert "config:" in decoded  # bug report
    for secret in (
        "secret-corp",
        "person@",
        "PROJ-1",
        SECRET_FIELD,
        summary,
        Path.home().name,
        str(Path(tendril.__file__).resolve().parents[2]),
    ):
        assert secret not in decoded, secret


async def test_trail_keeps_only_tendril_actions_and_screens(
    isolated_xdg: Path, load_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor moves, scrolls, Textual built-ins and the feedback modal stay out."""
    _seed(load_fixture)
    app = TendrilApp(Config(jira=JiraConfig(url="https://x", email="me@x")))
    monkeypatch.setattr(app, "open_url", lambda url, **_: None)

    async def open_feedback(pilot) -> None:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press(*"feedback")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause()

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "up", "down")  # DataTable cursor
        await pilot.press("S")  # TendrilApp.open_sprint_watchlist
        await pilot.pause()
        await pilot.press("m")  # SprintWatchlistScreen.toggle_mine_filter
        await pilot.press("escape")  # Textual pop -> "close"
        await pilot.pause()

        # A first feedback run, with scrolling inside the preview, then cancel.
        await open_feedback(pilot)
        await pilot.press("down", "down", "up", "escape")
        await pilot.pause()

        await open_feedback(pilot)
        from tendril.tui.screens.feedback_modal import FeedbackModal

        assert isinstance(app.screen, FeedbackModal)
        assert app.screen._ctx.recent_actions == (
            "open WatchlistScreen",
            "TendrilApp.open_sprint_watchlist",
            "open SprintWatchlistScreen",
            "SprintWatchlistScreen.toggle_mine_filter",
            "SprintWatchlistScreen.pop",
            "close SprintWatchlistScreen",
        )
