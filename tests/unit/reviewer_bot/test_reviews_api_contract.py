import pytest

from scripts.reviewer_bot_core import live_review_support
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


def test_get_pull_request_reviews_delegates_to_live_review_support(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    observed = {}

    def fake_read(bot, issue_number, reviews=None):
        observed.update({"bot": bot, "issue_number": issue_number, "reviews": reviews})
        return {"ok": True, "reviews": [{"id": 10}]}

    monkeypatch.setattr(live_review_support, "read_pull_request_reviews_result", fake_read)

    assert reviews.get_pull_request_reviews(runtime, 42) == [{"id": 10}]
    assert observed == {"bot": runtime, "issue_number": 42, "reviews": None}


def test_get_pull_request_reviews_fails_closed_when_live_review_read_fails(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    monkeypatch.setattr(
        live_review_support,
        "read_pull_request_reviews_result",
        lambda bot, issue_number, reviews=None: {"ok": False, "reason": "reviews_unavailable", "failure_kind": "server_error"},
    )

    assert reviews.get_pull_request_reviews(runtime, 42) is None
