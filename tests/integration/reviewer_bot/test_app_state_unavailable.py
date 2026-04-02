import pytest

from tests.fixtures.app_harness import AppHarness

pytestmark = pytest.mark.integration


def test_execute_run_mutating_event_fails_closed_when_state_unavailable(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.runtime.set_acquire_lock(lambda: None)
    harness.runtime.set_release_lock(lambda: True)
    harness.runtime.stub_state_unavailable("state unavailable")

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is False

def test_execute_run_mutating_event_does_not_sync_or_save_when_state_unavailable(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.runtime.set_acquire_lock(lambda: None)
    harness.runtime.set_release_lock(lambda: True)

    called = {
        "pass_until": False,
        "sync": False,
        "handler": False,
        "save": False,
    }

    def track_pass_until(state):
        called["pass_until"] = True
        return state, []

    def track_sync(state):
        called["sync"] = True
        return state, []

    def track_handler(state):
        called["handler"] = True
        return True

    def track_save(state):
        called["save"] = True
        return True

    harness.runtime.stub_state_unavailable("state unavailable")
    harness.runtime.set_pass_until(track_pass_until)
    harness.runtime.set_sync_members(track_sync)
    setattr(harness.runtime, "handle_comment_event", track_handler)
    harness.runtime.set_save_state(track_save)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert called == {
        "pass_until": False,
        "sync": False,
        "handler": False,
        "save": False,
    }
