import pytest

from scripts import reviewer_bot
from tests.fixtures.github import FakeGitHubResponse


def test_github_api_request_retries_idempotent_get_on_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests, "request", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1
    assert result.failure_kind is None


def test_github_api_request_retries_transport_exception_for_idempotent_get(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise reviewer_bot.github_api_module.requests.RequestException("timeout")
        return FakeGitHubResponse(200, {"ok": True}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1


def test_github_api_request_classifies_not_found_without_retry(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        return FakeGitHubResponse(404, {"message": "missing"}, "missing")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "not_found"
    assert result.retry_attempts == 0
    assert calls["count"] == 1


def test_github_api_request_classifies_forbidden_without_retry(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        return FakeGitHubResponse(403, {"message": "forbidden"}, "forbidden")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "forbidden"
    assert result.retry_attempts == 0
    assert calls["count"] == 1


def test_github_graphql_request_retries_idempotent_query_on_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok"),
        ]
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_graphql_request("query { viewer { login } }", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"data": {"viewer": {"login": "bot"}}}
    assert result.retry_attempts == 1


def test_github_api_request_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    responses = iter(
        [
            FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests, "request", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.retry_attempts == 1


def test_github_api_request_reports_retry_exhaustion_on_repeated_429(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "rate_limited"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT


def test_github_graphql_request_reports_invalid_payload(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "post",
        lambda *args, **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"),
    )

    result = reviewer_bot.github_graphql_request("query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_graphql_request_reports_graphql_errors(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "post",
        lambda *args, **kwargs: FakeGitHubResponse(200, {"errors": [{"message": "boom"}]}, "boom"),
    )

    result = reviewer_bot.github_graphql_request("query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_passes_timeout(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    observed = {}

    def fake_request(method, url, headers=None, json=None, timeout=None):
        observed["timeout"] = timeout
        return FakeGitHubResponse(200, {"ok": True}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request("GET", "issues/42", timeout_seconds=12.5)

    assert result.ok is True
    assert observed["timeout"] == 12.5


def test_github_api_request_rejects_idempotent_retry_for_non_get():
    with pytest.raises(ValueError, match="only valid for REST GET"):
        reviewer_bot.github_api_request("POST", "issues/42", retry_policy="idempotent_read")


def test_github_graphql_request_rejects_idempotent_retry_for_mutation():
    with pytest.raises(ValueError, match="only valid for GraphQL queries"):
        reviewer_bot.github_graphql_request(
            "mutation { closeIssue(input: {}) { clientMutationId } }",
            retry_policy="idempotent_read",
        )


def test_remove_label_reports_failure(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=500,
            payload={"message": "boom"},
            headers={},
            text="boom",
            ok=False,
            failure_kind="server_error",
            retry_attempts=0,
            transport_error=None,
        ),
    )

    assert reviewer_bot.remove_label(42, "status: awaiting reviewer response") is False


def test_get_user_permission_status_distinguishes_unavailable(monkeypatch):
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

    assert reviewer_bot.get_user_permission_status("alice", "triage") == "unavailable"
    assert reviewer_bot.check_user_permission("alice", "triage") is None


def test_get_issue_assignees_returns_none_when_fetch_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
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

    assert reviewer_bot.get_issue_assignees(42) is None


def test_find_open_pr_for_branch_status_reports_unavailable_for_malformed_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"not": "a list"},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("unavailable", None)


def test_find_open_pr_for_branch_status_reports_unavailable_on_transport_failure(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
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

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("unavailable", None)


def test_github_api_request_reports_invalid_payload_for_malformed_json(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"),
    )

    result = reviewer_bot.github_api_request("GET", "issues/42")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_reports_retry_exhaustion_on_repeated_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "server_error"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT


def test_github_api_request_reports_transport_retry_exhaustion(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")

    def always_fail(*args, **kwargs):
        raise reviewer_bot.github_api_module.requests.RequestException("timeout")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", always_fail)
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "transport_error"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT
    assert "timeout" in str(result.transport_error)


def test_github_graphql_request_passes_timeout(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    observed = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        observed["timeout"] = timeout
        return FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "post", fake_post)

    result = reviewer_bot.github_graphql_request("query { viewer { login } }", timeout_seconds=9.5)

    assert result.ok is True
    assert observed["timeout"] == 9.5


def test_find_open_pr_for_branch_status_blank_owner_or_branch_is_not_found(monkeypatch):
    monkeypatch.delenv("REPO_OWNER", raising=False)

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("not_found", None)
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    assert reviewer_bot.find_open_pr_for_branch_status("") == ("not_found", None)


def test_find_open_pr_for_branch_status_reports_found(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            [{"number": 42, "html_url": "https://example.com/pr/42"}],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    status, pr = reviewer_bot.find_open_pr_for_branch_status("feature")

    assert status == "found"
    assert pr == {"number": 42, "html_url": "https://example.com/pr/42"}


def test_find_open_pr_for_branch_status_reports_not_found_for_empty_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, [], {}, "ok", True, None, 0, None
        ),
    )

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("not_found", None)
