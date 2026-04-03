from scripts.reviewer_bot_lib import sweeper
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.github import FakeGitHubResponse
from tests.fixtures.reviewer_bot import make_zip_payload


def test_download_artifact_payload_retries_429_then_succeeds(monkeypatch):
    payload = {"source_event_key": "issue_comment:100"}
    responses = iter([FakeGitHubResponse(429, {"message": "slow down"}, "slow down")])
    success_response = FakeGitHubResponse(200, None, "")
    success_response.content = make_zip_payload("deferred-comment.json", payload)

    def fake_request(*args, **kwargs):
        return next(responses, success_response)

    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("GITHUB_TOKEN", "token")
    runtime.get_github_token = lambda: "token"
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sweeper.requests, "request", fake_request)
    runtime.requests = sweeper.requests

    status, artifact_payload = sweeper._download_artifact_payload(
        runtime,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "ok"
    assert artifact_payload == payload


def test_download_artifact_payload_reports_request_exception_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("GITHUB_TOKEN", "token")
    runtime.get_github_token = lambda: "token"
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(sweeper.requests.RequestException("timeout")),
    )
    runtime.requests = sweeper.requests

    status, payload = sweeper._download_artifact_payload(
        runtime,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None


def test_download_artifact_payload_reports_retry_exhaustion_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("GITHUB_TOKEN", "token")
    runtime.get_github_token = lambda: "token"
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
    )
    runtime.requests = sweeper.requests

    status, payload = sweeper._download_artifact_payload(
        runtime,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None


def test_list_run_artifacts_returns_none_when_api_payload_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    monkeypatch.setattr(sweeper, "_read_api_payload", lambda bot, endpoint: (None, "server_error"))

    assert sweeper._list_run_artifacts(runtime, 42) is None


def test_list_run_artifacts_consumes_retry_aware_success(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github_api_request = lambda method, endpoint, **kwargs: runtime.GitHubApiResult(
        status_code=200,
        payload={"artifacts": [{"id": 1, "name": "artifact"}]},
        headers={},
        text="ok",
        ok=True,
        failure_kind=None,
        retry_attempts=1,
        transport_error=None,
    )

    assert sweeper._list_run_artifacts(runtime, 10) == [{"id": 1, "name": "artifact"}]
