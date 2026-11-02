from __future__ import annotations

from typing import Any

from atlassian import Jira

from tendril.config import Config, get_token


class TendrilJira(Jira):
    """`atlassian.Jira` plus the Agile endpoints Tendril needs but the library lacks."""

    def rank_issues(self, data: dict) -> Any:
        return self.put(self.get_agile_resource_url("issue/rank"), data=data)


def build(cfg: Config) -> TendrilJira:
    """Return an authenticated `TendrilJira` client for Atlassian Cloud."""
    return TendrilJira(
        url=cfg.jira.url,
        username=cfg.jira.email,
        password=get_token(cfg.jira.email),
        cloud=True,
    )


def myself(client: Jira) -> dict:
    """Return the current user's profile (JIRA /myself)."""
    return client.myself()
