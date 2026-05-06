
from datetime import timezone

from scripts.reviewer_bot_core import live_review_support
from scripts.reviewer_bot_lib import reconcile_reads
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_pull_request_read_result_uses_fallback_payload_after_system_exit(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().raise_system_exit_on_request().add_api("GET", "pulls/42", {"head": {"sha": "head-1"}})
    runtime.github.stub(routes)

    result = live_review_support.read_pull_request_result(runtime, 42)

    assert result == {"ok": True, "pull_request": {"head": {"sha": "head-1"}}}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(404, {"message": "missing"}),
    )
    runtime.github.stub(routes)

    result = live_review_support.read_pull_request_result(runtime, 42)

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

    result = live_review_support.read_pull_request_result(runtime, 42)

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

    result = live_review_support.read_pull_request_reviews_result(runtime, 42)

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

    result = live_review_support.read_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42/reviews?per_page=100&page=1",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    runtime.github.stub(routes)

    result = live_review_support.read_pull_request_reviews_result(runtime, 42)

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

    result = live_review_support.read_pull_request_reviews_result(runtime, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_permission_status_fails_closed_for_unknown_values(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "mystery"

    assert live_review_support.permission_status(runtime, "alice", "push") == "unavailable"


def test_parse_github_timestamp_rejects_invalid_values():
    assert live_review_support.parse_github_timestamp(None) is None
    assert live_review_support.parse_github_timestamp("") is None
    assert live_review_support.parse_github_timestamp("not-a-timestamp") is None


def test_parse_github_timestamp_normalizes_timezone_less_values_to_utc():
    parsed = live_review_support.parse_github_timestamp("2026-04-02T00:00:00")

    assert parsed is not None
    assert parsed.tzinfo == timezone.utc
    assert parsed.isoformat() == "2026-04-02T00:00:00+00:00"


def test_review_dismissal_resolution_normalizes_timezone_less_payload_time(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    resolution = reconcile_reads.resolve_review_dismissal_time(
        runtime,
        42,
        12,
        {"source_dismissed_at": "2026-03-17T10:10:00"},
    )

    assert resolution.timestamp == "2026-03-17T10:10:00+00:00"
    assert resolution.source == "payload"


def test_review_dismissal_resolution_normalizes_timeline_time_to_canonical_utc(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.stub(
        RouteGitHubApi().add_request(
            "GET",
            "issues/42/timeline?per_page=100&page=1",
            status_code=200,
            payload=[
                {
                    "event": "review_dismissed",
                    "created_at": "2026-03-17T12:40:00+02:30",
                    "dismissed_review": {"review_id": 12},
                }
            ],
        )
    )

    resolution = reconcile_reads.resolve_review_dismissal_time(runtime, 42, 12, {})

    assert resolution.timestamp == "2026-03-17T10:10:00+00:00"
    assert resolution.source == "timeline"
