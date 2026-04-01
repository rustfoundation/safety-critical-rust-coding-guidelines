import pytest

from scripts import reviewer_bot


def test_list_open_items_with_status_labels_fails_closed_on_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="server_error"):
        reviewer_bot.list_open_items_with_status_labels()


def test_get_pull_request_reviews_result_paginates(monkeypatch):
    responses = {
        "pulls/42/reviews?per_page=100&page=1": reviewer_bot.GitHubApiResult(
            200, [{"id": i} for i in range(100)], {}, "ok", True, None, 0, None
        ),
        "pulls/42/reviews?per_page=100&page=2": reviewer_bot.GitHubApiResult(
            200, [{"id": 100}], {}, "ok", True, None, 0, None
        ),
    }
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: responses[endpoint],
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result["ok"] is True
    assert len(result["reviews"]) == 101


def test_get_pull_request_reviews_result_uses_fallback_loader_after_system_exit(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [{"id": 10}])

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, {"not": "a list"}, {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_not_found", "failure_kind": "not_found"}


def test_pull_request_read_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, ["not", "a", "dict"], {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}
