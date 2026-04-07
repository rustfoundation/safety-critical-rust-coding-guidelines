
from scripts.reviewer_bot_lib import review_read_support
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_pull_request_read_result_uses_fallback_payload_after_system_exit(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().raise_system_exit_on_request().add_api("GET", "pulls/42", {"head": {"sha": "head-1"}})
    runtime.github.stub(routes)

    result = review_read_support._pull_request_read_result(runtime, 42)

    assert result == {"ok": True, "pull_request": {"head": {"sha": "head-1"}}}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(404, {"message": "missing"}),
    )
    runtime.github.stub(routes)

    result = review_read_support._pull_request_read_result(runtime, 42)

    assert result == {"ok": False, "reason": "pull_request_not_found", "failure_kind": "not_found"}


def test_pull_request_read_result_reports_invalid_payload(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        status_code=200,
        payload=["not", "a", "dict"],
    )
    runtime.github.stub(routes)

    result = review_read_support._pull_request_read_result(runtime, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}


def test_get_pull_request_reviews_result_paginates(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
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
    runtime.github.stub(routes)

    result = review_read_support.get_pull_request_reviews_result(runtime, 42)

    assert result["ok"] is True
    assert len(result["reviews"]) == 101


def test_get_pull_request_reviews_result_uses_fallback_loader_after_system_exit(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().raise_system_exit_on_request().add_api(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        [{"id": 10}],
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [{"id": 10}]

    result = review_read_support.get_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    runtime.github.stub(routes)

    result = review_read_support.get_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "server_error"}


def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        status_code=200,
        payload={"not": "a list"},
    )
    runtime.github.stub(routes)

    result = review_read_support.get_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_permission_status_fails_closed_for_unknown_values(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "mystery"

    assert review_read_support._permission_status(runtime, "alice", "push") == "unavailable"


def test_parse_github_timestamp_rejects_invalid_values():
    assert review_read_support.parse_github_timestamp(None) is None
    assert review_read_support.parse_github_timestamp("") is None
    assert review_read_support.parse_github_timestamp("not-a-timestamp") is None
