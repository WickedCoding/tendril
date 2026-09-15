from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

import keyring
import tomli_w

APP_NAME = "tendril"
KEYRING_SERVICE = "tendril"

DEFAULT_SPRINT_PATTERN = r"^(?P<prefix>.*?)(?P<number>\d+)$"


def _xdg(env: str, fallback: Path) -> Path:
    val = os.environ.get(env)
    return Path(val) if val else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_NAME


@dataclass
class JiraConfig:
    url: str
    email: str
    account_id: str | None = None


@dataclass
class FieldsConfig:
    feature_flags: str | None = None
    sprint: str | None = None
    story_points: str | None = None
    skills: str | None = None


@dataclass
class LinksConfig:
    default_link_type: str = "Relates"


@dataclass
class SyncConfig:
    default_jql_extra: str = ""


DEFAULT_DONE_STATUSES: tuple[str, ...] = (
    "Ready for Acc",
    "Ready for Prod",
    "Closed",
    "Deployed to Acc",
    "Deployed to Prod",
)

DEFAULT_ROLLOVER_STATUSES: tuple[str, ...] = (
    "To Do",
    "In Progress",
    "Code Review",
    "Functional Review",
)

DEFAULT_SKILLS_TOTALS: tuple[str, ...] = ("Backend", "Frontend")


@dataclass
class OverviewConfig:
    done_statuses: list[str] = field(
        default_factory=lambda: list(DEFAULT_DONE_STATUSES)
    )


@dataclass
class SkillsConfig:
    """Which skill values roll up into per-skill totals on the rollover screen."""

    totals: list[str] = field(default_factory=lambda: list(DEFAULT_SKILLS_TOTALS))


@dataclass
class RolloverConfig:
    """Global rollover behaviour. Per-project overrides deferred until a real need surfaces."""

    statuses: list[str] = field(default_factory=lambda: list(DEFAULT_ROLLOVER_STATUSES))


@dataclass
class BoardConfig:
    """Per-project sprint-name pattern.

    An empty section is legal — `sprint_pattern` falls back to the default.
    Board pinning is not consumed anywhere yet; add it back once a caller needs it.
    """

    sprint_pattern: str = DEFAULT_SPRINT_PATTERN


@dataclass
class UIConfig:
    theme: str | None = None


@dataclass
class Config:
    jira: JiraConfig
    fields: FieldsConfig = field(default_factory=FieldsConfig)
    links: LinksConfig = field(default_factory=LinksConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    overview: OverviewConfig = field(default_factory=OverviewConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    rollover: RolloverConfig = field(default_factory=RolloverConfig)
    boards: dict[str, BoardConfig] = field(default_factory=dict)
    ui: UIConfig = field(default_factory=UIConfig)


class ConfigError(Exception):
    pass


def load() -> Config:
    path = config_path()
    if not path.exists():
        raise ConfigError(
            f"No config found at {path}. Run `tendril config init` first."
        )
    with path.open("rb") as f:
        raw = tomllib.load(f)

    jira_raw = raw.get("jira") or {}
    if "url" not in jira_raw or "email" not in jira_raw:
        raise ConfigError(f"{path} is missing [jira].url or [jira].email")

    overview_raw = raw.get("overview") or {}
    if "done_statuses" in overview_raw:
        done = overview_raw["done_statuses"]
        if not isinstance(done, list) or not all(isinstance(s, str) for s in done):
            raise ConfigError(
                f"{path} [overview].done_statuses must be a list of strings."
            )
        overview = OverviewConfig(done_statuses=list(done))
    else:
        overview = OverviewConfig()

    skills_raw = raw.get("skills") or {}
    if "totals" in skills_raw:
        totals = skills_raw["totals"]
        if not isinstance(totals, list) or not all(isinstance(s, str) for s in totals):
            raise ConfigError(f"{path} [skills].totals must be a list of strings.")
        skills = SkillsConfig(totals=list(totals))
    else:
        skills = SkillsConfig()

    rollover_raw = raw.get("rollover") or {}
    if "statuses" in rollover_raw:
        statuses = rollover_raw["statuses"]
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise ConfigError(f"{path} [rollover].statuses must be a list of strings.")
        rollover = RolloverConfig(statuses=list(statuses))
    else:
        rollover = RolloverConfig()

    boards_raw = raw.get("boards") or {}
    if not isinstance(boards_raw, dict):
        raise ConfigError(f"{path} [boards] must be a table of per-project sections.")
    boards: dict[str, BoardConfig] = {}
    for project_key, section in boards_raw.items():
        if not isinstance(section, dict):
            raise ConfigError(
                f"{path} [boards.{project_key}] must be a table."
            )
        pattern = section.get("sprint_pattern", DEFAULT_SPRINT_PATTERN)
        if not isinstance(pattern, str):
            raise ConfigError(
                f"{path} [boards.{project_key}].sprint_pattern must be a string."
            )
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            raise ConfigError(
                f"{path} [boards.{project_key}].sprint_pattern is not a valid regex: {e}"
            ) from e
        if "prefix" not in compiled.groupindex or "number" not in compiled.groupindex:
            raise ConfigError(
                f"{path} [boards.{project_key}].sprint_pattern must define named "
                "groups 'prefix' and 'number'."
            )
        boards[str(project_key)] = BoardConfig(sprint_pattern=pattern)

    ui_raw = raw.get("ui") or {}
    ui_theme = ui_raw.get("theme")
    if ui_theme is not None and not isinstance(ui_theme, str):
        raise ConfigError(f"{path} [ui].theme must be a string.")

    return Config(
        jira=JiraConfig(
            url=jira_raw["url"],
            email=jira_raw["email"],
            account_id=jira_raw.get("account_id"),
        ),
        fields=FieldsConfig(**(raw.get("fields") or {})),
        links=LinksConfig(**(raw.get("links") or {"default_link_type": "Relates"})),
        sync=SyncConfig(**(raw.get("sync") or {"default_jql_extra": ""})),
        overview=overview,
        skills=skills,
        rollover=rollover,
        boards=boards,
        ui=UIConfig(theme=ui_theme),
    )


def save(cfg: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    jira_payload = {"url": cfg.jira.url, "email": cfg.jira.email}
    if cfg.jira.account_id is not None:
        jira_payload["account_id"] = cfg.jira.account_id
    payload = {
        "jira": jira_payload,
        "fields": {
            k: v
            for k, v in {
                "feature_flags": cfg.fields.feature_flags,
                "sprint": cfg.fields.sprint,
                "story_points": cfg.fields.story_points,
                "skills": cfg.fields.skills,
            }.items()
            if v is not None
        },
        "links": {"default_link_type": cfg.links.default_link_type},
        "sync": {"default_jql_extra": cfg.sync.default_jql_extra},
        "overview": {"done_statuses": list(cfg.overview.done_statuses)},
        "skills": {"totals": list(cfg.skills.totals)},
        "rollover": {"statuses": list(cfg.rollover.statuses)},
    }
    if cfg.boards:
        boards_out: dict[str, dict] = {}
        for project_key, board in cfg.boards.items():
            section: dict = {}
            if board.sprint_pattern != DEFAULT_SPRINT_PATTERN:
                section["sprint_pattern"] = board.sprint_pattern
            boards_out[project_key] = section
        payload["boards"] = boards_out
    if cfg.ui.theme is not None:
        payload["ui"] = {"theme": cfg.ui.theme}
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
    return path


def get_token(email: str) -> str:
    try:
        token = keyring.get_password(KEYRING_SERVICE, email)
    except keyring.errors.KeyringError as e:
        raise ConfigError(
            f"Keyring backend refused to read the token: {e}. "
            "On macOS this usually means the login keychain is locked — unlock it and retry."
        ) from e
    if not token:
        raise ConfigError(
            f"No API token in keyring for {email}. Run `tendril config init`."
        )
    return token


def set_token(email: str, token: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, email, token)
    except keyring.errors.KeyringError as e:
        raise ConfigError(
            f"Keyring backend refused to store the token: {e}."
        ) from e


def delete_token(email: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, email)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        pass
