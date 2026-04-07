import pytest

from scripts.reviewer_bot_lib import maintenance, review_state, reviews
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_list_open_items_with_status_labels_fails_closed_on_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues?state=open&labels=status%3A%20awaiting%20contributor%20response&per_page=100&page=1",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    runtime.github.stub(routes)

    with pytest.raises(RuntimeError, match="server_error"):
        reviews.list_open_items_with_status_labels(runtime)


def test_collect_status_projection_repair_items_uses_review_support_listing_not_runtime_bag(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    runtime.list_open_items_with_status_labels = lambda: pytest.fail(
        "status projection repair collection must use review support, not runtime bag access"
    )
    monkeypatch.setattr(maintenance.reviews, "list_open_items_with_status_labels", lambda bot: [99, 42])

    assert maintenance.collect_status_projection_repair_items(runtime, state) == [42, 99]


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

    result = reviews.get_pull_request_reviews_result(runtime, 42)

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

    result = reviews.get_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        status_code=200,
        payload={"not": "a list"},
    )
    runtime.github.stub(routes)

    result = reviews.get_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(404, {"message": "missing"}),
    )
    runtime.github.stub(routes)

    result = reviews._pull_request_read_result(runtime, 42)

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

    result = reviews._pull_request_read_result(runtime, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}
