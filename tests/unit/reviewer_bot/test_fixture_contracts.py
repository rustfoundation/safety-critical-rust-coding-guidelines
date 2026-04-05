from datetime import datetime, timezone

from tests.fixtures.fake_clock import FakeClock
from tests.fixtures.fake_jitter import DeterministicJitter
from tests.fixtures.fake_sleeper import RecordingSleeper
from tests.fixtures.fake_uuid import FixedUuidSource
from tests.fixtures.focused_fake_services import (
    ArtifactDownloadTransportStub,
    GitHubStub,
    GraphQLTransportStub,
    LockStub,
    RestTransportStub,
    StateStoreStub,
    WorkflowBehaviorStub,
)
from tests.fixtures.recording_logger import RecordingLogger
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_shared_github_fixture_exports_core_transport_helpers():
    routes = RouteGitHubApi()
    result = github_result(200, {"ok": True})

    assert routes is not None
    assert result.ok is True


def test_shared_github_fixture_smoke_routes_simple_request():
    routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload={"head": {"sha": "head-1"}})

    result = routes.github_api_request("GET", "pulls/42")

    assert result.payload == {"head": {"sha": "head-1"}}


def test_fake_clock_can_set_and_advance_time():
    clock = FakeClock(datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc))

    assert clock.now() == datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc)
    clock.advance(seconds=30)
    assert clock.now() == datetime(2026, 3, 17, 10, 0, 30, tzinfo=timezone.utc)


def test_recording_sleeper_captures_sleep_calls():
    sleeper = RecordingSleeper()

    sleeper.sleep(1.5)
    sleeper.sleep(2.0)

    assert sleeper.calls == [1.5, 2.0]


def test_deterministic_jitter_replays_configured_values():
    jitter = DeterministicJitter([0.5, 0.75])

    assert jitter.uniform(0.1, 1.0) == 0.5
    assert jitter.uniform(0.1, 1.0) == 0.75
    assert jitter.uniform(0.1, 1.0) == 0.75
    assert jitter.calls == [(0.1, 1.0), (0.1, 1.0), (0.1, 1.0)]


def test_fixed_uuid_source_replays_values_and_records_issued_ids():
    source = FixedUuidSource(["uuid-1", "uuid-2"])

    assert source.uuid4_hex() == "uuid-1"
    assert source.uuid4_hex() == "uuid-2"
    assert source.uuid4_hex() == "uuid-2"
    assert source.issued == ["uuid-1", "uuid-2", "uuid-2"]


def test_recording_logger_captures_structured_events():
    logger = RecordingLogger()

    logger.event("warning", "retrying request", issue_number=42, retry_attempt=2)

    assert logger.records == [
        {
            "level": "warning",
            "message": "retrying request",
            "fields": {"issue_number": 42, "retry_attempt": 2},
        }
    ]


def test_graphql_transport_stub_replays_sequence_and_keeps_last_value():
    transport = GraphQLTransportStub()
    transport.stub_sequence([{"data": {"viewer": {"login": "bot"}}}, {"data": {"viewer": {"login": "bot-2"}}}])

    assert transport.query("https://api.github.com/graphql", query="q") == {"data": {"viewer": {"login": "bot"}}}
    assert transport.query("https://api.github.com/graphql", query="q") == {"data": {"viewer": {"login": "bot-2"}}}
    assert transport.query("https://api.github.com/graphql", query="q") == {"data": {"viewer": {"login": "bot-2"}}}


def test_rest_transport_stub_routes_repo_urls_through_github_stub():
    github = GitHubStub(RouteGitHubApi().add_request("GET", "issues/42", result=github_result(200, {"ok": True})))
    transport = RestTransportStub(github)

    response = transport.request("GET", "https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/42")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert transport.calls[0]["url"].endswith("issues/42")


def test_artifact_download_transport_stub_replays_sequence_and_raises_exceptions():
    transport = ArtifactDownloadTransportStub()
    transport.stub_sequence([RuntimeError("timeout"), {"ok": True}])

    try:
        transport.download("https://example.com/artifact.zip")
    except RuntimeError as exc:
        assert "timeout" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert transport.download("https://example.com/artifact.zip") == {"ok": True}
    assert transport.download("https://example.com/artifact.zip") == {"ok": True}


def test_state_store_stub_records_load_and_save_calls():
    store = StateStoreStub()
    store.stub_load(lambda *, fail_on_unavailable=False: {"active_reviews": {"42": {}}})
    store.stub_save(lambda state: True)

    assert store.load_state(fail_on_unavailable=True) == {"active_reviews": {"42": {}}}
    assert store.save_state({"active_reviews": {"42": {"current_reviewer": "alice"}}}) is True
    assert store.load_calls == [{"fail_on_unavailable": True}]
    assert store.save_calls == [{"active_reviews": {"42": {"current_reviewer": "alice"}}}]


def test_lock_stub_records_acquire_release_refresh_calls():
    lock = LockStub()
    lock.stub(acquire=lambda: "token", release=lambda: True, refresh=lambda: False)

    assert lock.acquire() == "token"
    assert lock.refresh() is False
    assert lock.release() is True
    assert lock.calls == ["acquire", "refresh", "release"]


def test_workflow_behavior_stub_records_behavior_calls():
    workflow = WorkflowBehaviorStub()
    workflow.stub_pass_until(lambda state: ({**state, "restored": True}, ["alice"]))
    workflow.stub_sync_members(lambda state: ({**state, "synced": True}, ["bob"]))
    workflow.stub_sync_status_labels(lambda state, issue_numbers: True)

    state = {"active_reviews": {}}
    assert workflow.process_pass_until_expirations(state) == ({"active_reviews": {}, "restored": True}, ["alice"])
    assert workflow.sync_members_with_queue(state) == ({"active_reviews": {}, "synced": True}, ["bob"])
    assert workflow.sync_status_labels_for_items(state, [42, 99]) is True
    assert [call["name"] for call in workflow.calls] == [
        "process_pass_until_expirations",
        "sync_members_with_queue",
        "sync_status_labels_for_items",
    ]
