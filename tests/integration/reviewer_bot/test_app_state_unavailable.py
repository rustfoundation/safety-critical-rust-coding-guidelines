from scripts import reviewer_bot
import pytest

pytestmark = pytest.mark.integration

def test_execute_run_mutating_event_fails_closed_when_state_unavailable(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)

    def fail_load(*, fail_on_unavailable=False):
        assert fail_on_unavailable is True
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(reviewer_bot, "load_state", fail_load)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert result.state_changed is False

def test_execute_run_mutating_event_does_not_sync_or_save_when_state_unavailable(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)

    called = {
        "pass_until": False,
        "sync": False,
        "handler": False,
        "save": False,
    }

    def fail_load(*, fail_on_unavailable=False):
        assert fail_on_unavailable is True
        raise RuntimeError("state unavailable")

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

    monkeypatch.setattr(reviewer_bot, "load_state", fail_load)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", track_pass_until)
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", track_sync)
    monkeypatch.setattr(reviewer_bot, "handle_comment_event", track_handler)
    monkeypatch.setattr(reviewer_bot, "save_state", track_save)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert called == {
        "pass_until": False,
        "sync": False,
        "handler": False,
        "save": False,
    }
