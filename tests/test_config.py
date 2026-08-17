from __future__ import annotations

from pathlib import Path

import pytest

from tendril import config as cfg_mod
from tendril.config import Config, ConfigError, FieldsConfig, JiraConfig, LinksConfig, SyncConfig


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


def test_save_omits_none_field_ids(isolated_xdg: Path) -> None:
    original = Config(
        jira=JiraConfig(url="https://acme.atlassian.net", email="me@example.com"),
    )
    cfg_mod.save(original)
    contents = cfg_mod.config_path().read_text()
    assert "feature_flags" not in contents
    assert "sprint" not in contents
