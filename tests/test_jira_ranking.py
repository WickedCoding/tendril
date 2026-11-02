"""Exercise ranking through the real installed Atlassian client, without Jira I/O."""

import json
from unittest.mock import patch

import pytest
from requests import HTTPError, Response

from tendril.config import Config, JiraConfig
from tendril.jira.client import TendrilJira, build
from tendril.jira.write import rank_issues_in_order


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TendrilJira:
    monkeypatch.setattr("tendril.jira.client.get_token", lambda email: "offline")
    return build(Config(jira=JiraConfig(url="https://example.atlassian.net", email="offline")))


def _response(status: int = 204) -> Response:
    response = Response()
    response.status_code = status
    response._content = b""
    response.url = "https://example.atlassian.net/rest/agile/1.0/issue/rank"
    return response


@pytest.mark.parametrize("count", [2, 52, 120])
def test_real_jira_client_sends_rank_after_batches(client: TendrilJira, count: int) -> None:
    keys = [f"KEY-{i}" for i in range(count)]
    with patch("requests.Session.send", return_value=_response()) as send:
        rank_issues_in_order(client, keys)

    seen = []
    anchor = keys[0]
    for call in send.call_args_list:
        request = call.args[0]
        assert request.method == "PUT"
        assert request.url == "https://example.atlassian.net/rest/agile/1.0/issue/rank"
        body = json.loads(request.body)
        assert body["rankAfterIssue"] == anchor
        assert 1 <= len(body["issues"]) <= 49
        seen.extend(body["issues"])
        anchor = body["issues"][-1]
    assert seen == keys[1:]


@pytest.mark.parametrize("keys", [[], ["KEY-1"]])
def test_real_jira_client_does_not_request_a_trivial_ranking(client: TendrilJira, keys: list[str]) -> None:
    with patch("requests.Session.send") as send:
        rank_issues_in_order(client, keys)
    send.assert_not_called()


def test_real_jira_client_propagates_rank_failure_without_sending_later_batches(client: TendrilJira) -> None:
    with patch("requests.Session.send", return_value=_response(403)) as send:
        with pytest.raises(HTTPError):
            rank_issues_in_order(client, [f"KEY-{i}" for i in range(120)])
    assert send.call_count == 1
