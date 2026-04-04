from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import automation, github_api
from scripts.reviewer_bot_lib.config import LOCK_API_RETRY_LIMIT, GitHubApiResult
from tests.fixtures.http_responses import FakeGitHubResponse


class RecordingRestTransport:
    def __init__(self, responses=None):
        self._responses = iter(responses or [])
        self.calls = []

    def request(self, method, url, *, headers=None, json_data=None, timeout_seconds=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json_data": json_data,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _bot(**overrides):
    bot = SimpleNamespace(
        GitHubApiResult=GitHubApiResult,
        get_github_token=lambda: "token",
        get_github_graphql_token=lambda prefer_board_token=False: "token",
        get_config_value=lambda name, default="": __import__("os").environ.get(name, default),
        rest_transport=RecordingRestTransport(),
        STATE_ISSUE_NUMBER=1,
    )
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot


def test_github_api_request_retries_idempotent_get_on_502(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1
    assert result.failure_kind is None


def test_github_api_request_retries_transport_exception_for_idempotent_get(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport(
        [github_api.requests.RequestException("timeout"), FakeGitHubResponse(200, {"ok": True}, "ok")]
    )
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1


def test_github_api_request_classifies_not_found_without_retry(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(404, {"message": "missing"}, "missing")])

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "not_found"
    assert result.retry_attempts == 0
    assert len(transport.calls) == 1


def test_github_api_request_classifies_forbidden_without_retry(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(403, {"message": "forbidden"}, "forbidden")])

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "forbidden"
    assert result.retry_attempts == 0
    assert len(transport.calls) == 1


def test_github_graphql_request_retries_idempotent_query_on_502(monkeypatch):
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok"),
        ]
    )
    monkeypatch.setattr(github_api.requests, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_graphql_request(_bot(), "query { viewer { login } }", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"data": {"viewer": {"login": "bot"}}}
    assert result.retry_attempts == 1


def test_github_api_request_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport(
        [
            FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.retry_attempts == 1


def test_github_api_request_reports_retry_exhaustion_on_repeated_429(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(429, {"message": "slow down"}, "slow down")] * (LOCK_API_RETRY_LIMIT + 1))
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "rate_limited"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT


def test_github_graphql_request_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(github_api.requests, "post", lambda *args, **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"))

    result = github_api.github_graphql_request(_bot(), "query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_graphql_request_reports_graphql_errors(monkeypatch):
    monkeypatch.setattr(github_api.requests, "post", lambda *args, **kwargs: FakeGitHubResponse(200, {"errors": [{"message": "boom"}]}, "boom"))

    result = github_api.github_graphql_request(_bot(), "query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_passes_timeout(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(200, {"ok": True}, "ok")])

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", timeout_seconds=12.5)

    assert result.ok is True
    assert transport.calls[0]["timeout_seconds"] == 12.5


def test_github_api_request_rejects_idempotent_retry_for_non_get():
    with pytest.raises(ValueError, match="only valid for REST GET"):
        github_api.github_api_request(_bot(), "POST", "issues/42", retry_policy="idempotent_read")


def test_github_graphql_request_rejects_idempotent_retry_for_mutation():
    with pytest.raises(ValueError, match="only valid for GraphQL queries"):
        github_api.github_graphql_request(
            _bot(),
            "mutation { closeIssue(input: {}) { clientMutationId } }",
            retry_policy="idempotent_read",
        )


def test_remove_label_reports_failure():
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=500, payload={"message": "boom"}, headers={}, text="boom", ok=False, failure_kind="server_error", retry_attempts=0, transport_error=None))

    assert github_api.remove_label(bot, 42, "status: awaiting reviewer response") is False


def test_get_user_permission_status_distinguishes_unavailable():
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None))

    assert github_api.get_user_permission_status(bot, "alice", "triage") == "unavailable"
    assert github_api.check_user_permission(bot, "alice", "triage") is None


def test_get_issue_assignees_returns_none_when_fetch_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None), github_api=lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))

    assert github_api.get_issue_assignees(bot, 42) is None


def test_find_open_pr_for_branch_status_reports_unavailable_for_malformed_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=200, payload={"not": "a list"}, headers={}, text="ok", ok=True, failure_kind=None, retry_attempts=0, transport_error=None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("unavailable", None)


def test_find_open_pr_for_branch_status_reports_unavailable_on_transport_failure(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("unavailable", None)


def test_github_api_request_reports_invalid_payload_for_malformed_json(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(200, ValueError("bad json"), "bad json")])

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_reports_retry_exhaustion_on_repeated_502(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway")] * (LOCK_API_RETRY_LIMIT + 1))
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "server_error"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT


def test_github_api_request_reports_transport_retry_exhaustion(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    transport = RecordingRestTransport([github_api.requests.RequestException("timeout")] * (LOCK_API_RETRY_LIMIT + 1))
    monkeypatch.setattr(github_api.time, "sleep", lambda *_args, **_kwargs: None)

    result = github_api.github_api_request(_bot(rest_transport=transport), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "transport_error"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT
    assert "timeout" in str(result.transport_error)


def test_github_graphql_request_passes_timeout(monkeypatch):
    observed = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        observed["timeout"] = timeout
        return FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok")

    monkeypatch.setattr(github_api.requests, "post", fake_post)

    result = github_api.github_graphql_request(_bot(), "query { viewer { login } }", timeout_seconds=9.5)

    assert result.ok is True
    assert observed["timeout"] == 9.5


def test_find_open_pr_for_branch_status_blank_owner_or_branch_is_not_found(monkeypatch):
    monkeypatch.delenv("REPO_OWNER", raising=False)

    assert automation.find_open_pr_for_branch_status(_bot(), "feature") == ("not_found", None)
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    assert automation.find_open_pr_for_branch_status(_bot(), "") == ("not_found", None)


def test_find_open_pr_for_branch_status_reports_found(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(200, [{"number": 42, "html_url": "https://example.com/pr/42"}], {}, "ok", True, None, 0, None))

    status, pr = automation.find_open_pr_for_branch_status(bot, "feature")

    assert status == "found"
    assert pr == {"number": 42, "html_url": "https://example.com/pr/42"}


def test_find_open_pr_for_branch_status_reports_not_found_for_empty_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    bot = _bot(github_api_request=lambda *args, **kwargs: GitHubApiResult(200, [], {}, "ok", True, None, 0, None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("not_found", None)
