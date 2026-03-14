import pytest

from scripts import reviewer_bot


def make_state():
    return {
        "last_updated": None,
        "current_index": 0,
        "queue": [
            {"github": "alice", "name": "Alice"},
            {"github": "bob", "name": "Bob"},
            {"github": "carol", "name": "Carol"},
        ],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }


def test_classify_event_intent_cross_repo_review_is_non_mutating_defer(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_same_repo_review_is_mutating(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "false")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_MUTATING


def test_classify_event_intent_same_repo_dismissed_review_is_mutating(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "false")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "dismissed")
    assert intent == reviewer_bot.EVENT_INTENT_MUTATING


def test_classify_event_intent_workflow_run_dismissed_review_is_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "dismissed")
    intent = reviewer_bot.classify_event_intent("workflow_run", "completed")
    assert intent == reviewer_bot.EVENT_INTENT_MUTATING


def test_main_cross_repo_review_does_not_acquire_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fail_if_called)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is False


def test_main_same_repo_review_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "false")

    acquire_called = {"value": False}

    def fake_acquire():
        acquire_called["value"] = True
        return reviewer_bot.LeaseContext(
            lock_token="token",
            lock_owner_run_id="run",
            lock_owner_workflow="workflow",
            lock_owner_job="job",
            state_issue_url="https://example.com/issues/314",
            lock_ref="refs/heads/reviewer-bot-state-lock",
            lock_expires_at="2999-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fake_acquire)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is True


def test_main_reloads_state_before_syncing_status_labels(monkeypatch):
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

    reviewer_bot.main()

    assert call_order == ["load:1", "handle", "save", "load:2", "sync"]


def test_main_fails_when_save_state_fails(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_comment_event", lambda state: True)
    monkeypatch.setattr(reviewer_bot, "save_state", lambda state: False)

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1


def test_main_workflow_run_fails_closed_on_invalid_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "submitted")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1


def test_main_mutating_event_fails_closed_when_state_unavailable(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)

    def fail_load(*, fail_on_unavailable=False):
        assert fail_on_unavailable is True
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(reviewer_bot, "load_state", fail_load)

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1


def test_main_mutating_event_does_not_sync_or_save_when_state_unavailable(monkeypatch):
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

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1
    assert called == {
        "pass_until": False,
        "sync": False,
        "handler": False,
        "save": False,
    }


def test_schedule_guard_blocks_empty_active_reviews_wipe(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)

    state = make_state()
    state["active_reviews"] = {
        "42": {
            "current_reviewer": "alice",
            "assigned_at": "2026-01-01T00:00:00+00:00",
            "last_reviewer_activity": "2026-01-01T00:00:00+00:00",
        }
    }

    def wipe_active_reviews(input_state):
        input_state["active_reviews"] = {}
        return True

    save_called = {"value": False}

    def track_save(_state):
        save_called["value"] = True
        return True

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "handle_scheduled_check", wipe_active_reviews)
    monkeypatch.setattr(reviewer_bot, "save_state", track_save)

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1
    assert save_called["value"] is False
