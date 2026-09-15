from __future__ import annotations

from pathlib import Path

import pytest

from tendril import config as cfg_mod
from tendril.config import (
    BoardConfig,
    Config,
    ConfigError,
    DEFAULT_ROLLOVER_STATUSES,
    DEFAULT_SKILLS_TOTALS,
    DEFAULT_SPRINT_PATTERN,
    FieldsConfig,
    JiraConfig,
    LinksConfig,
    OverviewConfig,
    RolloverConfig,
    SkillsConfig,
    SyncConfig,
    UIConfig,
)


def test_paths_honour_xdg(isolated_xdg: Path) -> None:
    assert cfg_mod.config_path() == isolated_xdg / "config" / "tendril" / "config.toml"
    assert cfg_mod.data_dir() == isolated_xdg / "data" / "tendril"


def test_save_then_load_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://acme.atlassian.net", email="me@example.com"),
        fields=FieldsConfig(feature_flags="customfield_12345", sprint="customfield_10020"),
        links=LinksConfig(default_link_type="Blocks"),
        sync=SyncConfig(default_jql_extra="project = FOO"),
    )
    path = cfg_mod.save(original)
    assert path.exists()

    loaded = cfg_mod.load()
    assert loaded.jira.url == "https://acme.atlassian.net"
    assert loaded.jira.email == "me@example.com"
    assert loaded.fields.feature_flags == "customfield_12345"
    assert loaded.fields.sprint == "customfield_10020"
    assert loaded.links.default_link_type == "Blocks"
    assert loaded.sync.default_jql_extra == "project = FOO"


def test_load_missing_raises(isolated_xdg: Path) -> None:
    with pytest.raises(ConfigError, match="No config found"):
        cfg_mod.load()


def test_load_missing_jira_section_raises(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[fields]\nfeature_flags = "customfield_1"\n')
    with pytest.raises(ConfigError, match="missing"):
        cfg_mod.load()


def test_get_token_wraps_keyring_backend_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring
    from keyring.errors import KeyringError

    def _blow_up(service, user):
        raise KeyringError("backend not available")

    monkeypatch.setattr(keyring, "get_password", _blow_up)
    with pytest.raises(ConfigError, match="Keyring backend"):
        cfg_mod.get_token("me@example.com")


def test_get_token_missing_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)
    with pytest.raises(ConfigError, match="Run `tendril config init`"):
        cfg_mod.get_token("me@example.com")


def test_save_omits_none_field_ids(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://acme.atlassian.net", email="me@example.com"),
    )
    cfg_mod.save(original)
    contents = cfg_mod.config_path().read_text()
    assert "feature_flags" not in contents
    assert "sprint" not in contents


def test_overview_done_statuses_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://acme.atlassian.net", email="me@example.com"),
        overview=OverviewConfig(done_statuses=["Done", "Won't Fix"]),
    )
    cfg_mod.save(original)
    loaded = cfg_mod.load()
    assert loaded.overview.done_statuses == ["Done", "Won't Fix"]


def test_overview_defaults_when_section_absent(isolated_xdg: Path) -> None:
    cfg_mod.save(Config(jira=JiraConfig(url="https://x", email="me@x")))
    # Rewrite without the [overview] section to simulate an older config.
    path = cfg_mod.config_path()
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
    )
    loaded = cfg_mod.load()
    assert "Closed" in loaded.overview.done_statuses
    assert "Deployed to Prod" in loaded.overview.done_statuses


def test_ui_theme_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        ui=UIConfig(theme="nord"),
    )
    cfg_mod.save(original)
    assert 'theme = "nord"' in cfg_mod.config_path().read_text()
    assert cfg_mod.load().ui.theme == "nord"


def test_ui_omitted_when_theme_none(isolated_xdg: Path) -> None:
    cfg_mod.save(Config(jira=JiraConfig(url="https://x", email="me@x")))
    assert "[ui]" not in cfg_mod.config_path().read_text()
    assert cfg_mod.load().ui.theme is None


def test_ui_rejects_non_string_theme(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n[ui]\ntheme = 3\n'
    )
    with pytest.raises(ConfigError, match="theme"):
        cfg_mod.load()


def test_overview_rejects_non_string_statuses(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        "[overview]\ndone_statuses = [1, 2]\n"
    )
    with pytest.raises(ConfigError, match="done_statuses"):
        cfg_mod.load()


def test_story_points_and_skills_fields_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        fields=FieldsConfig(
            story_points="customfield_10032",
            skills="customfield_10134",
        ),
    )
    cfg_mod.save(original)
    loaded = cfg_mod.load()
    assert loaded.fields.story_points == "customfield_10032"
    assert loaded.fields.skills == "customfield_10134"


def test_skills_totals_defaults_when_section_absent(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[jira]\nurl = "https://x"\nemail = "me@x"\n')
    loaded = cfg_mod.load()
    assert loaded.skills.totals == list(DEFAULT_SKILLS_TOTALS)


def test_skills_totals_custom_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        skills=SkillsConfig(totals=["Backend", "Frontend", "Data"]),
    )
    cfg_mod.save(original)
    loaded = cfg_mod.load()
    assert loaded.skills.totals == ["Backend", "Frontend", "Data"]


def test_skills_rejects_non_string_totals(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        "[skills]\ntotals = [1, 2]\n"
    )
    with pytest.raises(ConfigError, match=r"\[skills\]\.totals"):
        cfg_mod.load()


def test_rollover_statuses_defaults_when_section_absent(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[jira]\nurl = "https://x"\nemail = "me@x"\n')
    loaded = cfg_mod.load()
    assert loaded.rollover.statuses == list(DEFAULT_ROLLOVER_STATUSES)


def test_rollover_statuses_custom_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        rollover=RolloverConfig(statuses=["To Do", "Blocked"]),
    )
    cfg_mod.save(original)
    loaded = cfg_mod.load()
    assert loaded.rollover.statuses == ["To Do", "Blocked"]


def test_rollover_rejects_non_string_statuses(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        "[rollover]\nstatuses = [1, 2]\n"
    )
    with pytest.raises(ConfigError, match=r"\[rollover\]\.statuses"):
        cfg_mod.load()


def test_boards_roundtrip(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        boards={
            "MMINT": BoardConfig(
                sprint_pattern=r"^(?P<prefix>MM-)(?P<number>\d+)$",
            ),
        },
    )
    cfg_mod.save(original)
    loaded = cfg_mod.load()
    assert "MMINT" in loaded.boards
    assert loaded.boards["MMINT"].sprint_pattern == r"^(?P<prefix>MM-)(?P<number>\d+)$"


def test_boards_default_pattern_when_omitted(isolated_xdg: Path) -> None:
    """An empty board section is legal — the sprint pattern falls back to the default."""
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        "[boards.MMINT]\n"
    )
    loaded = cfg_mod.load()
    assert "MMINT" in loaded.boards
    assert loaded.boards["MMINT"].sprint_pattern == DEFAULT_SPRINT_PATTERN


def test_boards_default_pattern_omitted_from_saved_file(isolated_xdg: Path) -> None:
    """Sprint pattern at the default value shouldn't clutter the saved TOML."""
    original = Config(
        jira=JiraConfig(url="https://x", email="me@x"),
        boards={"MMINT": BoardConfig()},
    )
    cfg_mod.save(original)
    contents = cfg_mod.config_path().read_text()
    assert "[boards.MMINT]" in contents
    assert "sprint_pattern" not in contents


def test_boards_rejects_invalid_regex(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        '[boards.MMINT]\nsprint_pattern = "(unbalanced"\n'
    )
    with pytest.raises(ConfigError, match="valid regex"):
        cfg_mod.load()


def test_boards_rejects_pattern_missing_named_groups(isolated_xdg: Path) -> None:
    path = cfg_mod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[jira]\nurl = "https://x"\nemail = "me@x"\n'
        '[boards.MMINT]\nsprint_pattern = "^(.*)$"\n'
    )
    with pytest.raises(ConfigError, match="named groups"):
        cfg_mod.load()
