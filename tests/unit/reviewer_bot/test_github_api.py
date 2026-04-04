import pytest

from scripts.reviewer_bot_lib import automation, github_api
from scripts.reviewer_bot_lib.config import LOCK_API_RETRY_LIMIT, GitHubApiResult
from tests.fixtures.fake_jitter import DeterministicJitter
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.fake_sleeper import RecordingSleeper
from tests.fixtures.http_responses import FakeGitHubResponse
from tests.fixtures.recording_logger import RecordingLogger
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def _bot(monkeypatch, *, config=None, github=None, **overrides):
    bot = FakeReviewerBotRuntime(monkeypatch, github=github)
    bot.logger = RecordingLogger()
    bot.sleeper = RecordingSleeper()
    bot.jitter = DeterministicJitter(0.0)
    bot.set_config_value("REPO_OWNER", "rustfoundation")
    bot.set_config_value("REPO_NAME", "safety-critical-rust-coding-guidelines")
    bot.set_config_value("GITHUB_TOKEN", "token")
    for name, value in (config or {}).items():
        bot.set_config_value(name, value)
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot


def test_github_api_request_retries_idempotent_get_on_502(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [
            github_result(502, {"message": "bad gateway"}),
            github_result(200, {"ok": True}),
        ],
    )
    bot = _bot(monkeypatch, github=github)
    result = github_api.github_api_request(bot, "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1
    assert result.failure_kind is None
    assert bot.sleeper.calls == [2.0]


def test_github_api_request_retries_transport_exception_for_idempotent_get(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [github_api.requests.RequestException("timeout"), github_result(200, {"ok": True})],
    )
    bot = _bot(monkeypatch, github=github)
    result = github_api.github_api_request(bot, "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1
    assert bot.sleeper.calls == [2.0]


def test_github_api_request_classifies_not_found_without_retry(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "issues/42", result=github_result(404, {"message": "missing"}))
    bot = _bot(monkeypatch, github=github)
    result = github_api.github_api_request(bot, "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "not_found"
    assert result.retry_attempts == 0
    assert github.requested_endpoints() == ["issues/42"]


def test_github_api_request_classifies_forbidden_without_retry(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "issues/42", result=github_result(403, {"message": "forbidden"}))
    bot = _bot(monkeypatch, github=github)
    result = github_api.github_api_request(bot, "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "forbidden"
    assert result.retry_attempts == 0
    assert github.requested_endpoints() == ["issues/42"]


def test_github_graphql_request_retries_idempotent_query_on_502(monkeypatch):
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok"),
        ]
    )
    bot = _bot(monkeypatch)
    bot.graphql_transport.stub(lambda **kwargs: next(responses))
    result = github_api.github_graphql_request(
        bot,
        "query { viewer { login } }",
        retry_policy="idempotent_read",
    )

    assert result.ok is True
    assert result.payload == {"data": {"viewer": {"login": "bot"}}}
    assert result.retry_attempts == 1


def test_github_api_request_retries_rate_limit_then_succeeds(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [
            github_result(429, {"message": "slow down"}),
            github_result(200, {"ok": True}),
        ],
    )
    result = github_api.github_api_request(_bot(monkeypatch, github=github), "GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.retry_attempts == 1


def test_github_api_request_reports_retry_exhaustion_on_repeated_429(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [github_result(429, {"message": "slow down"})] * (LOCK_API_RETRY_LIMIT + 1),
    )
    result = github_api.github_api_request(_bot(monkeypatch, github=github), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "rate_limited"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT


def test_github_graphql_request_reports_invalid_payload(monkeypatch):
    bot = _bot(monkeypatch)
    bot.graphql_transport.stub(lambda **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"))

    result = github_api.github_graphql_request(bot, "query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_graphql_request_reports_graphql_errors(monkeypatch):
    bot = _bot(monkeypatch)
    bot.graphql_transport.stub(lambda **kwargs: FakeGitHubResponse(200, {"errors": [{"message": "boom"}]}, "boom"))

    result = github_api.github_graphql_request(bot, "query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_passes_timeout(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "issues/42", result=github_result(200, {"ok": True}))
    bot = _bot(monkeypatch, github=github)

    result = github_api.github_api_request(bot, "GET", "issues/42", timeout_seconds=12.5)

    assert result.ok is True
    assert bot.rest_transport.calls[0]["timeout_seconds"] == 12.5


def test_github_api_request_rejects_idempotent_retry_for_non_get(monkeypatch):
    with pytest.raises(ValueError, match="only valid for REST GET"):
        github_api.github_api_request(_bot(monkeypatch), "POST", "issues/42", retry_policy="idempotent_read")


def test_github_graphql_request_rejects_idempotent_retry_for_mutation(monkeypatch):
    with pytest.raises(ValueError, match="only valid for GraphQL queries"):
        github_api.github_graphql_request(
            _bot(monkeypatch),
            "mutation { closeIssue(input: {}) { clientMutationId } }",
            retry_policy="idempotent_read",
        )


def test_remove_label_reports_failure(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=500, payload={"message": "boom"}, headers={}, text="boom", ok=False, failure_kind="server_error", retry_attempts=0, transport_error=None))

    assert github_api.remove_label(bot, 42, "status: awaiting reviewer response") is False


def test_get_user_permission_status_distinguishes_unavailable(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None))

    assert github_api.get_user_permission_status(bot, "alice", "triage") == "unavailable"
    assert github_api.check_user_permission(bot, "alice", "triage") is None


def test_get_issue_assignees_returns_none_when_fetch_unavailable(monkeypatch):
    bot = _bot(monkeypatch, config={"IS_PULL_REQUEST": "true"}, github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None), github_api=lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))

    assert github_api.get_issue_assignees(bot, 42) is None


def test_request_reviewer_assignment_uses_runtime_config_for_pr_target(monkeypatch):
    recorded = {}

    def fake_request(method, endpoint, data=None, suppress_error_log=True, **kwargs):
        recorded.update({"method": method, "endpoint": endpoint, "data": data})
        return GitHubApiResult(201, {}, {}, "ok", True, None, 0, None)

    bot = _bot(monkeypatch, config={"IS_PULL_REQUEST": "true"}, github_api_request=fake_request)

    result = github_api.request_reviewer_assignment(bot, 42, "alice")

    assert result.success is True
    assert recorded == {
        "method": "POST",
        "endpoint": "pulls/42/requested_reviewers",
        "data": {"reviewers": ["alice"]},
    }


def test_request_reviewer_assignment_uses_runtime_config_for_issue_target(monkeypatch):
    recorded = {}

    def fake_request(method, endpoint, data=None, suppress_error_log=True, **kwargs):
        recorded.update({"method": method, "endpoint": endpoint, "data": data})
        return GitHubApiResult(201, {}, {}, "ok", True, None, 0, None)

    bot = _bot(monkeypatch, config={"IS_PULL_REQUEST": "false"}, github_api_request=fake_request)

    result = github_api.request_reviewer_assignment(bot, 42, "alice")

    assert result.success is True
    assert recorded == {
        "method": "POST",
        "endpoint": "issues/42/assignees",
        "data": {"assignees": ["alice"]},
    }


def test_get_assignment_failure_comment_uses_runtime_config_for_pr_message(monkeypatch):
    bot = _bot(monkeypatch, config={"IS_PULL_REQUEST": "true"})
    failed = bot.AssignmentAttempt(success=False, status_code=422)

    assert "PR Reviewers" in github_api.get_assignment_failure_comment(bot, "alice", failed)


def test_unassign_reviewer_uses_runtime_config_to_remove_pr_reviewer(monkeypatch):
    calls = []
    bot = _bot(
        monkeypatch,
        config={"IS_PULL_REQUEST": "true"},
        remove_pr_reviewer=lambda issue_number, username: calls.append(("pr", issue_number, username)) or True,
        remove_assignee=lambda issue_number, username: calls.append(("issue", issue_number, username)) or True,
    )

    assert github_api.unassign_reviewer(bot, 42, "alice") is True
    assert calls == [("pr", 42, "alice"), ("issue", 42, "alice")]


def test_find_open_pr_for_branch_status_reports_unavailable_for_malformed_payload(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=200, payload={"not": "a list"}, headers={}, text="ok", ok=True, failure_kind=None, retry_attempts=0, transport_error=None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("unavailable", None)


def test_find_open_pr_for_branch_status_reports_unavailable_on_transport_failure(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(status_code=502, payload={"message": "bad gateway"}, headers={}, text="bad gateway", ok=False, failure_kind="server_error", retry_attempts=1, transport_error=None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("unavailable", None)


def test_github_api_request_reports_invalid_payload_for_malformed_json(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "issues/42", result=github_result(200, ValueError("bad json"), text="bad json"))
    result = github_api.github_api_request(_bot(monkeypatch, github=github), "GET", "issues/42")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_reports_retry_exhaustion_on_repeated_502(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [github_result(502, {"message": "bad gateway"})] * (LOCK_API_RETRY_LIMIT + 1),
    )
    result = github_api.github_api_request(_bot(monkeypatch, github=github), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "server_error"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT


def test_github_api_request_reports_transport_retry_exhaustion(monkeypatch):
    github = RouteGitHubApi().add_request_sequence(
        "GET",
        "issues/42",
        [github_api.requests.RequestException("timeout")] * (LOCK_API_RETRY_LIMIT + 1),
    )
    result = github_api.github_api_request(_bot(monkeypatch, github=github), "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "transport_error"
    assert result.retry_attempts == LOCK_API_RETRY_LIMIT
    assert "timeout" in str(result.transport_error)


def test_github_api_request_logs_transport_error_to_recording_logger(monkeypatch):
    github = RouteGitHubApi().add_request_sequence("GET", "issues/42", [github_api.requests.RequestException("timeout")])
    bot = _bot(monkeypatch, github=github)

    result = github_api.github_api_request(bot, "GET", "issues/42", suppress_error_log=False)

    assert result.ok is False
    assert bot.logger.records[-1]["level"] == "error"
    assert "transport error" in bot.logger.records[-1]["message"]


def test_github_api_request_logs_error_response_to_recording_logger(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "issues/42", result=github_result(403, {"message": "forbidden"}))
    bot = _bot(monkeypatch, github=github)

    result = github_api.github_api_request(bot, "GET", "issues/42", suppress_error_log=False)

    assert result.ok is False
    assert bot.logger.records[-1]["level"] == "error"
    assert bot.logger.records[-1]["fields"]["status_code"] == 403


def test_github_graphql_request_passes_timeout(monkeypatch):
    bot = _bot(monkeypatch)
    bot.graphql_transport.stub(lambda **kwargs: FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok"))

    result = github_api.github_graphql_request(bot, "query { viewer { login } }", timeout_seconds=9.5)

    assert result.ok is True
    assert bot.graphql_transport.calls[0]["timeout_seconds"] == 9.5


def test_find_open_pr_for_branch_status_blank_owner_or_branch_is_not_found(monkeypatch):
    assert automation.find_open_pr_for_branch_status(_bot(monkeypatch, config={"REPO_OWNER": ""}), "feature") == ("not_found", None)
    assert automation.find_open_pr_for_branch_status(_bot(monkeypatch), "") == ("not_found", None)


def test_find_open_pr_for_branch_status_reports_found(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(200, [{"number": 42, "html_url": "https://example.com/pr/42"}], {}, "ok", True, None, 0, None))

    status, pr = automation.find_open_pr_for_branch_status(bot, "feature")

    assert status == "found"
    assert pr == {"number": 42, "html_url": "https://example.com/pr/42"}


def test_find_open_pr_for_branch_status_reports_not_found_for_empty_payload(monkeypatch):
    bot = _bot(monkeypatch, github_api_request=lambda *args, **kwargs: GitHubApiResult(200, [], {}, "ok", True, None, 0, None))

    assert automation.find_open_pr_for_branch_status(bot, "feature") == ("not_found", None)
