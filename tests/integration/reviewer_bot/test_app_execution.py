from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state
import pytest

pytestmark = pytest.mark.integration

def test_execute_run_reloads_state_before_syncing_status_labels(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")

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
        reviewer_bot.collect_touched_item(42)
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

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_comment_event", fake_handle_comment_event)
    monkeypatch.setattr(reviewer_bot, "save_state", fake_save_state)
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", fake_sync_status_labels_for_items)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

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
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_comment_event", lambda state: True)
    monkeypatch.setattr(reviewer_bot, "save_state", lambda state: False)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert result.state_changed is True

def test_execute_run_returns_failure_for_invalid_workflow_run_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "submitted")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(
        reviewer_bot,
        "handle_workflow_run_event",
        lambda state: (_ for _ in ()).throw(RuntimeError("invalid deferred context")),
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert result.state_changed is False
