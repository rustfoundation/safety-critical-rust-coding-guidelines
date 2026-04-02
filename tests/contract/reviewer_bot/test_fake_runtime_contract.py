import pytest

from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.github import RouteGitHubApi

pytestmark = pytest.mark.contract


def test_fake_runtime_config_writes_mirror_env(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.set_config_value("EVENT_NAME", "issue_comment")

    assert runtime.get_config_value("EVENT_NAME") == "issue_comment"


def test_fake_runtime_output_sink_records_writes(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    runtime.write_output("state_changed", "true")

    assert runtime.outputs.writes == [("state_changed", "true")]


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
    runtime.set_acquire_lock(lambda: calls.append("acquire") or None)
    runtime.set_release_lock(lambda: calls.append("release") or True)

    assert runtime.acquire_state_issue_lease_lock() is None
    assert runtime.release_state_issue_lease_lock() is True
    assert calls == ["acquire", "release"]


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
