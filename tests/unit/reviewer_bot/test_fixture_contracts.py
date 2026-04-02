import pytest

from tests.fixtures.github import RouteGitHubApi, github_result


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


def test_route_github_api_supports_invalid_payload_routes():
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
