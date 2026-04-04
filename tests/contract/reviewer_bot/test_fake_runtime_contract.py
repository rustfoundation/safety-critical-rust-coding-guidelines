import pytest

from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.focused_fake_services import (
    ArtifactDownloadTransportStub,
    ConfigBag,
    DeferredPayloadStore,
    GitHubStub,
    GraphQLTransportStub,
    HandlerStub,
    LockStub,
    OutputCapture,
    RestTransportStub,
    StateStoreStub,
    TouchTrackerStub,
    WorkflowBehaviorStub,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.contract


def test_fake_runtime_config_writes_round_trip_locally(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.set_config_value("EVENT_NAME", "issue_comment")

    assert runtime.get_config_value("EVENT_NAME") == "issue_comment"
    assert hasattr(FakeReviewerBotRuntime, "__getattr__") is False
    assert "_module" not in vars(runtime)


def test_fake_runtime_exposes_explicit_service_fields_and_no_omnibus_service_container(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert runtime.config is not None
    assert runtime.outputs is not None
    assert runtime.deferred_payloads is not None
    assert runtime.logger is not None
    assert runtime.state_store is not None
    assert runtime.github is not None
    assert runtime.locks is not None
    assert runtime.handlers is not None
    assert runtime.touch_tracker is not None
    assert runtime.infra is not None
    assert runtime.domain is not None
    assert hasattr(runtime, "services") is False
    assert hasattr(runtime, "components") is False


def test_fake_runtime_exposes_no_class_level_module_authority_hints(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    module_hints = sorted(name for name in vars(FakeReviewerBotRuntime) if name.endswith("_module"))

    assert module_hints == []
    assert hasattr(runtime, "review_state_module") is False
    assert hasattr(runtime, "reviews_module") is False


def test_fake_runtime_output_sink_records_writes(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.write_output("state_changed", "true")

    assert runtime.outputs.writes == [("state_changed", "true")]


def test_fake_runtime_recording_logger_captures_structured_events(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.logger.event("warning", "retrying", issue_number=42, retry_attempt=2)

    assert runtime.logger.records == [
        {
            "level": "warning",
            "message": "retrying",
            "fields": {"issue_number": 42, "retry_attempt": 2},
        }
    ]


def test_fake_runtime_touched_items_preserve_uniqueness_and_drain(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.collect_touched_item(42)
    runtime.collect_touched_item(42)
    runtime.collect_touched_item(99)

    assert runtime.drain_touched_items() == [42, 99]
    assert runtime.drain_touched_items() == []


def test_fake_runtime_stub_state_sequence_replays_until_last_snapshot(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.stub_state_sequence({"active_reviews": {"42": {}}}, {"active_reviews": {}})

    first = runtime.load_state()
    second = runtime.load_state()
    third = runtime.load_state()

    assert first == {"active_reviews": {"42": {}}}
    assert second == {"active_reviews": {}}
    assert third == {"active_reviews": {}}


def test_fake_runtime_stub_state_unavailable_requires_fail_closed_load(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.stub_state_unavailable("state unavailable")

    with pytest.raises(RuntimeError, match="state unavailable"):
        runtime.load_state(fail_on_unavailable=True)


def test_fake_runtime_record_saves_captures_structured_snapshots(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    snapshots = []
    runtime.record_saves(snapshots)

    state = {"active_reviews": {"42": {"current_reviewer": "alice"}}}
    assert runtime.save_state(state) is True
    state["active_reviews"]["42"]["current_reviewer"] = "bob"

    assert snapshots == [{"active_reviews": {"42": {"current_reviewer": "alice"}}}]


def test_fake_runtime_optional_lock_hooks_are_replaceable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    calls = []
    runtime.stub_lock(acquire=lambda: calls.append("acquire") or None, release=lambda: calls.append("release") or True)

    assert runtime.acquire_state_issue_lease_lock() is None
    assert runtime.release_state_issue_lease_lock() is True
    assert calls == ["acquire", "release"]


def test_fake_runtime_uses_explicit_public_service_fields(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert runtime.config is not None
    assert runtime.outputs is not None
    assert runtime.deferred_payloads is not None
    assert runtime.state_store is not None
    assert runtime.github is not None
    assert runtime.locks is not None
    assert runtime.touch_tracker is not None


def test_fake_runtime_review_state_compatibility_surface_is_limited(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    allowed = {"ensure_review_entry", "set_current_reviewer", "update_reviewer_activity", "mark_review_complete"}
    removed = {"record_transition_notice_sent", "accept_channel_event", "record_reviewer_activity", "get_current_cycle_boundary"}

    for name in allowed:
        assert hasattr(runtime, name)
    for name in removed:
        assert hasattr(runtime, name) is False


def test_fake_runtime_rejects_unknown_handler_names(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    with pytest.raises(AssertionError, match="Unsupported runtime handler override"):
        runtime.handlers.stub("handle_everything", lambda state: False)


def test_fake_runtime_github_transport_delegates_to_shared_route_fake(monkeypatch):
    github = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload={"head": {"sha": "head-1"}})
    runtime = FakeReviewerBotRuntime(monkeypatch, github=github)

    result = runtime.github_api_request("GET", "pulls/42")

    assert result.ok is True
    assert result.payload == {"head": {"sha": "head-1"}}


def test_fake_runtime_github_api_mode_delegates_to_shared_route_fake(monkeypatch):
    github = RouteGitHubApi().add_api("GET", "pulls/42", {"head": {"sha": "head-1"}})
    runtime = FakeReviewerBotRuntime(monkeypatch, github=github)

    assert runtime.github_api("GET", "pulls/42") == {"head": {"sha": "head-1"}}


def test_focused_fake_service_types_are_exposed_for_direct_fixture_composition(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert isinstance(runtime.config, ConfigBag)
    assert isinstance(runtime.outputs, OutputCapture)
    assert isinstance(runtime.deferred_payloads, DeferredPayloadStore)
    assert isinstance(runtime.state_store, StateStoreStub)
    assert isinstance(runtime.github, GitHubStub)
    assert isinstance(runtime.locks, LockStub)
    assert isinstance(runtime.rest_transport, RestTransportStub)
    assert isinstance(runtime.graphql_transport, GraphQLTransportStub)
    assert isinstance(runtime.artifact_download_transport, ArtifactDownloadTransportStub)
    assert isinstance(runtime.handlers, HandlerStub)
    assert isinstance(runtime.touch_tracker, TouchTrackerStub)
    assert isinstance(runtime.workflow, WorkflowBehaviorStub)


def test_fake_runtime_groups_focused_services_into_infra_and_domain_shells(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert runtime.infra.config is runtime.config
    assert runtime.infra.outputs is runtime.outputs
    assert runtime.infra.deferred_payloads is runtime.deferred_payloads
    assert runtime.infra.logger is runtime.logger
    assert runtime.infra.rest_transport is runtime.rest_transport
    assert runtime.infra.graphql_transport is runtime.graphql_transport
    assert runtime.infra.artifact_download_transport is runtime.artifact_download_transport
    assert runtime.infra.touch_tracker is runtime.touch_tracker
    assert runtime.domain.state_store is runtime.state_store
    assert runtime.domain.github is runtime.github
    assert runtime.domain.locks is runtime.locks
    assert runtime.domain.handlers is runtime.handlers
    assert runtime.domain.workflow is runtime.workflow
