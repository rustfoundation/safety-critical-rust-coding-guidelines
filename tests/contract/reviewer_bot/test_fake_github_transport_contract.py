import pytest

from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result

pytestmark = pytest.mark.contract


def test_github_result_builds_success_shape():
    result = github_result(200, {"ok": True}, headers={"ETag": "abc"})

    assert result.status_code == 200
    assert result.payload == {"ok": True}
    assert result.headers == {"etag": "abc"}
    assert result.ok is True
    assert result.failure_kind is None


def test_github_result_builds_not_found_shape():
    result = github_result(404, {"message": "missing"})

    assert result.ok is False
    assert result.failure_kind == "not_found"
    assert result.text == "missing"


def test_github_result_builds_server_error_shape():
    result = github_result(502, {"message": "bad gateway"})

    assert result.ok is False
    assert result.failure_kind == "server_error"
    assert result.text == "bad gateway"


def test_route_github_api_request_supports_invalid_payload_routes():
    routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload=["not", "a", "dict"])

    result = routes.github_api_request("GET", "pulls/42")

    assert result.ok is True
    assert result.payload == ["not", "a", "dict"]


def test_route_github_api_raises_system_exit_on_request_and_keeps_api_mode():
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42/reviews?per_page=100&page=1", [{"id": 10}])
        .raise_system_exit_on_request()
    )

    with pytest.raises(SystemExit):
        routes.github_api_request("GET", "pulls/42/reviews?per_page=100&page=1")

    assert routes.github_api("GET", "pulls/42/reviews?per_page=100&page=1") == [{"id": 10}]


def test_route_github_api_supports_paginated_review_endpoints():
    routes = (
        RouteGitHubApi()
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[{"id": index} for index in range(100)],
        )
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=2",
            status_code=200,
            payload=[{"id": 100}],
        )
    )

    first = routes.github_api_request("GET", "pulls/42/reviews?per_page=100&page=1")
    second = routes.github_api_request("GET", "pulls/42/reviews?per_page=100&page=2")

    assert len(first.payload) == 100
    assert second.payload == [{"id": 100}]
    assert routes.requested_endpoints() == [
        "pulls/42/reviews?per_page=100&page=1",
        "pulls/42/reviews?per_page=100&page=2",
    ]


def test_route_github_api_add_pull_request_snapshot_registers_api_and_request_modes():
    routes = RouteGitHubApi().add_pull_request_snapshot(42, {"head": {"sha": "head-1"}})

    assert routes.github_api("GET", "pulls/42") == {"head": {"sha": "head-1"}}
    result = routes.github_api_request("GET", "pulls/42")
    assert result.ok is True
    assert result.payload == {"head": {"sha": "head-1"}}


def test_route_github_api_add_pull_request_reviews_registers_page_route():
    routes = RouteGitHubApi().add_pull_request_reviews(42, [{"id": 10}], page=2)

    result = routes.github_api_request("GET", "pulls/42/reviews?per_page=100&page=2")

    assert result.ok is True
    assert result.payload == [{"id": 10}]


def test_route_github_api_request_sequence_replays_retryable_failures_then_success():
    routes = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [
            github_result(429, {"message": "slow down"}),
            github_result(502, {"message": "bad gateway"}),
            github_result(200, {"ok": True}),
        ],
    )

    first = routes.github_api_request("GET", "issues/42")
    second = routes.github_api_request("GET", "issues/42")
    third = routes.github_api_request("GET", "issues/42")
    fourth = routes.github_api_request("GET", "issues/42")

    assert first.failure_kind == "rate_limited"
    assert second.failure_kind == "server_error"
    assert third.ok is True
    assert fourth.ok is True


def test_route_github_api_request_sequence_can_raise_then_return_success():
    routes = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [RuntimeError("timeout"), github_result(200, {"ok": True})],
    )

    with pytest.raises(RuntimeError, match="timeout"):
        routes.github_api_request("GET", "issues/42")

    result = routes.github_api_request("GET", "issues/42")

    assert result.ok is True
    assert result.payload == {"ok": True}


def test_route_github_api_api_sequence_replays_values_and_keeps_last_value():
    routes = RouteGitHubApi().add_api_sequence(
        "GET",
        "pulls/42",
        [{"head": {"sha": "head-1"}}, {"head": {"sha": "head-2"}}],
    )

    assert routes.github_api("GET", "pulls/42") == {"head": {"sha": "head-1"}}
    assert routes.github_api("GET", "pulls/42") == {"head": {"sha": "head-2"}}
    assert routes.github_api("GET", "pulls/42") == {"head": {"sha": "head-2"}}
