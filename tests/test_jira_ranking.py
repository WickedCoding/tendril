"""Exercise ranking through the real installed Atlassian client, without Jira I/O."""

import json
from unittest.mock import patch

import pytest
from atlassian import Jira
from requests import HTTPError, Response

from tendril.jira.write import rank_issues_in_order


def _response(status: int = 204) -> Response:
    response = Response()
    response.status_code = status
    response._content = b""
    response.url = "https://example.atlassian.net/rest/agile/1.0/issue/rank"
    return response


@pytest.mark.parametrize("count", [2, 52, 120])
def test_real_jira_client_sends_rank_after_batches(count: int) -> None:
    client = Jira(url="https://example.atlassian.net", username="offline", password="offline", cloud=True)
    keys = [f"KEY-{i}" for i in range(count)]
    with patch.object(client._session, "send", return_value=_response()) as send:
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
def test_real_jira_client_does_not_request_a_trivial_ranking(keys: list[str]) -> None:
    client = Jira(url="https://example.atlassian.net", username="offline", password="offline", cloud=True)
    with patch.object(client._session, "send") as send:
        rank_issues_in_order(client, keys)
    send.assert_not_called()


def test_real_jira_client_propagates_rank_failure_without_sending_later_batches() -> None:
    client = Jira(url="https://example.atlassian.net", username="offline", password="offline", cloud=True)
    with patch.object(client._session, "send", return_value=_response(403)) as send:
        with pytest.raises(HTTPError):
            rank_issues_in_order(client, [f"KEY-{i}" for i in range(120)])
    assert send.call_count == 1
