import pytest

from scripts import reviewer_bot
from tests.fixtures.github import RouteGitHubApi, github_result


def test_list_open_items_with_status_labels_fails_closed_on_unavailable(monkeypatch):
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues?state=open&labels=status%3A%20awaiting%20contributor%20response&per_page=100&page=1",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    with pytest.raises(RuntimeError, match="server_error"):
        reviewer_bot.list_open_items_with_status_labels()


def test_get_pull_request_reviews_result_paginates(monkeypatch):
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
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result["ok"] is True
    assert len(result["reviews"]) == 101


def test_get_pull_request_reviews_result_uses_fallback_loader_after_system_exit(monkeypatch):
    routes = RouteGitHubApi().raise_system_exit_on_request().add_api(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        [{"id": 10}],
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        status_code=200,
        payload={"not": "a list"},
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(404, {"message": "missing"}),
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_not_found", "failure_kind": "not_found"}


def test_pull_request_read_result_reports_invalid_payload(monkeypatch):
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        status_code=200,
        payload=["not", "a", "dict"],
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}
