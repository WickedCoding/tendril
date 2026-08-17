from __future__ import annotations

from atlassian import Jira

from tendril.config import Config, get_token


def build(cfg: Config) -> Jira:
    """Return an authenticated `atlassian.Jira` client for Atlassian Cloud."""
    return Jira(
        url=cfg.jira.url,
        username=cfg.jira.email,
        password=get_token(cfg.jira.email),
        cloud=True,
    )


def myself(client: Jira) -> dict:
    """Return the current user's profile (JIRA /myself)."""
    return client.myself()
