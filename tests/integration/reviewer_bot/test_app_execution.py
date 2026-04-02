import pytest

from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


def test_execute_run_reloads_state_before_syncing_status_labels(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")

    initial_state = make_state()
    reloaded_state = make_state()
    load_calls = {"count": 0}
    call_order = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        call_order.append(f"load:{load_calls['count']}")
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    def fake_handle_comment_event(state):
        assert state is initial_state
        harness.runtime.collect_touched_item(42)
        call_order.append("handle")
        return True

    def fake_save_state(state):
        assert state is initial_state
        call_order.append("save")
        return True

    def fake_sync_status_labels_for_items(state, issue_numbers):
        call_order.append("sync")
        assert state is reloaded_state
        assert list(issue_numbers) == [42]
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", fake_handle_comment_event)
    harness.stub_save_state(fake_save_state)
    harness.stub_sync_status_labels(fake_sync_status_labels_for_items)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert call_order == [
        "load:1",
        "handle",
        "load:2",
        "save",
        "load:3",
        "load:4",
        "sync",
    ]

def test_execute_run_returns_failure_when_save_state_fails(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    harness.stub_save_state(lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is True

def test_execute_run_returns_failure_for_invalid_workflow_run_context(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="pull_request_review",
        WORKFLOW_RUN_EVENT_ACTION="submitted",
    )
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_workflow_run_event", lambda state: (_ for _ in ()).throw(RuntimeError("invalid deferred context")))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is False
