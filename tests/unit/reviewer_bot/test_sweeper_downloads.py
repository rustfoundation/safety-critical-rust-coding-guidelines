from scripts.reviewer_bot_lib import sweeper
from tests.fixtures.fake_jitter import DeterministicJitter
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.fake_sleeper import RecordingSleeper
from tests.fixtures.http_responses import FakeGitHubResponse
from tests.fixtures.reviewer_bot import make_zip_payload


def test_download_artifact_payload_retries_429_then_succeeds(monkeypatch):
    payload = {"source_event_key": "issue_comment:100"}
    responses = iter([FakeGitHubResponse(429, {"message": "slow down"}, "slow down")])
    success_response = FakeGitHubResponse(200, None, "")
    success_response.content = make_zip_payload("deferred-comment.json", payload)

    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("GITHUB_TOKEN", "token")
    runtime.get_github_token = lambda: "token"
    runtime.jitter = DeterministicJitter(0.5)
    runtime.sleeper = RecordingSleeper()
    runtime.artifact_download_transport.stub_sequence([*responses, success_response])

    status, artifact_payload = sweeper._download_artifact_payload(
        runtime,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "ok"
    assert artifact_payload == payload
    assert runtime.sleeper.calls == [2.5]
    assert runtime.artifact_download_transport.calls[0]["url"] == "https://example.com/artifact.zip"


def test_download_retry_delay_uses_shared_backoff_with_jitter(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.jitter = DeterministicJitter([0.25, 0.5, 0.75])

    assert sweeper._download_retry_delay(runtime, 1) == 2.25
    assert sweeper._download_retry_delay(runtime, 2) == 4.5
    assert sweeper._download_retry_delay(runtime, 3) == 8.75


def test_download_artifact_payload_reports_request_exception_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("GITHUB_TOKEN", "token")
    runtime.get_github_token = lambda: "token"
    runtime.sleeper = RecordingSleeper()
    runtime.artifact_download_transport.stub_sequence([RuntimeError("timeout")])

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
    runtime.sleeper = RecordingSleeper()
    runtime.artifact_download_transport.stub_sequence([FakeGitHubResponse(429, {"message": "slow down"}, "slow down")] * 6)

    status, payload = sweeper._download_artifact_payload(
        runtime,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None
    assert len(runtime.sleeper.calls) == 5


def test_list_run_artifacts_returns_none_when_api_payload_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github_api_request = lambda method, endpoint, **kwargs: runtime.GitHubApiResult(
        status_code=502,
        payload={"message": "bad gateway"},
        headers={},
        text="bad gateway",
        ok=False,
        failure_kind="server_error",
        retry_attempts=1,
        transport_error=None,
    )

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
