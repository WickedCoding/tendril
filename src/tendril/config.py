from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

import keyring
import tomli_w

APP_NAME = "tendril"
KEYRING_SERVICE = "tendril"


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


@dataclass
class OverviewConfig:
    done_statuses: list[str] = field(
        default_factory=lambda: list(DEFAULT_DONE_STATUSES)
    )


@dataclass
class Config:
    jira: JiraConfig
    fields: FieldsConfig = field(default_factory=FieldsConfig)
    links: LinksConfig = field(default_factory=LinksConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    overview: OverviewConfig = field(default_factory=OverviewConfig)


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
            }.items()
            if v is not None
        },
        "links": {"default_link_type": cfg.links.default_link_type},
        "sync": {"default_jql_extra": cfg.sync.default_jql_extra},
        "overview": {"done_statuses": list(cfg.overview.done_statuses)},
    }
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
