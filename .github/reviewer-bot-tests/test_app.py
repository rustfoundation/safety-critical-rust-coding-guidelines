import json

import pytest
from factories import make_state
from factories import valid_reviewer_board_metadata as _valid_reviewer_board_metadata

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.lifecycle import HeadObservationRepairResult


def test_main_show_state_uses_direct_yaml_import(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "show-state")
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())

    reviewer_bot.main()

    output = capsys.readouterr().out
    assert "Current state:" in output
    assert "freshness_runtime_epoch" in output

def test_classify_event_intent_cross_repo_review_is_non_mutating_defer(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER

def test_classify_event_intent_preview_reviewer_board_is_non_mutating(monkeypatch):
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    intent = reviewer_bot.classify_event_intent("workflow_dispatch", "")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_READONLY

def test_classify_event_intent_same_repo_review_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER

def test_classify_event_intent_same_repo_dismissed_review_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review", "dismissed")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER

def test_classify_event_intent_review_comment_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review_comment", "created")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER

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

def test_main_same_repo_review_does_not_acquire_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fail_if_called)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is False

def test_main_workflow_run_reconcile_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")

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
    monkeypatch.setattr(reviewer_bot, "handle_workflow_run_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is True

def test_main_workflow_run_review_comment_reconcile_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")

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
    monkeypatch.setattr(reviewer_bot, "handle_workflow_run_event", lambda state: False)

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

    assert call_order == [
        "load:1",
        "handle",
        "load:2",
        "save",
        "load:3",
        "load:4",
        "sync",
    ]

def test_main_preview_reviewer_board_disabled_is_clean_noop(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "false")

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should not save state")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda state, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")),
    )

    reviewer_bot.main()

    output = capsys.readouterr().out
    assert "Reviewer board preview skipped: reviewer board is disabled." in output

def test_main_preview_reviewer_board_missing_token_fails_clearly(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1
    assert "REVIEWER_BOARD_TOKEN not set" in capsys.readouterr().err

def test_main_preview_reviewer_board_invalid_manifest_fails_clearly(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_graphql",
        lambda query, variables=None, *, token=None: {
            "data": {
                "organization": {
                    "projectV2": {
                        "id": "PVT_kwDOB",
                        "title": "Reviewer Board",
                        "fields": {"nodes": []},
                    }
                }
            }
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1
    assert "Missing reviewer board field: Review State" in capsys.readouterr().err

def test_main_preview_reviewer_board_is_read_only(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")),
    )
    monkeypatch.setattr(reviewer_bot, "github_graphql", lambda query, variables=None, *, token=None: _valid_reviewer_board_metadata())
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    reviewer_bot.main()

    output = capsys.readouterr().out
    assert "classification: open_tracked_assigned" in output
    assert "ensure_membership: true" in output

def test_issue_close_then_close_comment_does_not_leave_active_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_TITLE", "Validation issue")
    monkeypatch.setenv("ISSUE_BODY", "body")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation close-path comment")

    assert reviewer_bot.handle_closed_event(state) is True
    assert "42" not in state["active_reviews"]
    assert reviewer_bot.handle_comment_event(state) is False
    assert "42" not in state["active_reviews"]

def test_main_closed_issue_comment_cleanup_persists_removed_review_entry(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation close-path comment")

    initial_state = make_state()
    review = reviewer_bot.ensure_review_entry(initial_state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    reloaded_state = make_state()
    load_calls = {"count": 0}
    save_calls = []
    sync_calls = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda state: save_calls.append("42" in state["active_reviews"]) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda state, issue_numbers: sync_calls.append((state, list(issue_numbers))) or True,
    )

    reviewer_bot.main()

    assert save_calls == [False]
    assert len(sync_calls) == 1
    assert sync_calls[0][0] is reloaded_state
    assert sync_calls[0][1] == [42]

def test_main_closed_issue_comment_without_entry_skips_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation close-path comment")

    state = make_state()
    save_called = {"value": False}
    sync_calls = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_called.__setitem__("value", True) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: sync_calls.append(list(issue_numbers)) or False,
    )

    reviewer_bot.main()

    assert save_called["value"] is False
    assert sync_calls == [[42]]

def test_main_label_signoff_issue_saves_before_status_projection(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")

    initial_state = make_state()
    review = reviewer_bot.ensure_review_entry(initial_state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    reloaded_state = make_state()
    load_calls = {"count": 0}
    call_order = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: call_order.append("save") or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: call_order.append("sync") or current is reloaded_state,
    )

    reviewer_bot.main()

    assert initial_state["active_reviews"]["42"]["review_completion_source"] == "issue_label: sign-off: create pr"
    assert call_order == ["save", "sync"]

def test_main_label_signoff_issue_does_not_project_labels_when_save_fails(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "save_state", lambda current: False)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(
            AssertionError("status projection must not run after failed save")
        ),
    )

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1

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
    monkeypatch.setattr(
        reviewer_bot,
        "handle_workflow_run_event",
        lambda state: (_ for _ in ()).throw(RuntimeError("invalid deferred context")),
    )

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1

def test_main_schedule_backfills_existing_transition_notice_without_duplicate_comment(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "check_overdue_reviews",
        lambda bot, current: [
            {
                "issue_number": 42,
                "reviewer": "alice",
                "days_overdue": 20,
                "days_since_warning": 15,
                "needs_warning": False,
                "needs_transition": True,
            }
        ],
    )
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []})
    save_calls = []
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_calls.append(current["active_reviews"]["42"]["transition_notice_sent_at"]) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    def fake_api(method, endpoint, data=None):
        if endpoint == "issues/42/comments?per_page=100":
            return [{"id": 99, "created_at": "2026-03-25T15:22:42Z", "body": "🔔 **Transition Period Ended**\n\nExisting notice", "user": {"login": "github-actions[bot]"}}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_api)
    reviewer_bot.main()
    assert review["transition_notice_sent_at"] == "2026-03-25T15:22:42Z"
    assert posted == []
    assert save_calls == ["2026-03-25T15:22:42Z"]

def test_main_schedule_reviewer_review_repair_marks_item_for_label_sync(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"

    synced_issue_numbers = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "COMMENTED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )
    save_calls = []
    monkeypatch.setattr(reviewer_bot, "save_state", lambda current: save_calls.append(current) or True)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True,
    )

    reviewer_bot.main()

    assert review["reviewer_review"]["accepted"]["semantic_key"] == "pull_request_review:10"
    assert synced_issue_numbers == [42]
    assert len(save_calls) == 1

def test_main_schedule_structured_head_repair_result_without_mutation_skips_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_called = {"value": False}

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_called.__setitem__("value", True) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("no touched items expected")),
    )

    reviewer_bot.main()

    assert save_called["value"] is False

def test_main_schedule_status_projection_epoch_mismatch_triggers_label_repair_sweep(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    synced_issue_numbers = []
    saved_epochs = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "handle_scheduled_check", lambda current: False)
    monkeypatch.setattr(reviewer_bot, "list_open_items_with_status_labels", lambda: [99])
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: saved_epochs.append(current.get("status_projection_epoch")) or True,
    )

    reviewer_bot.main()

    assert synced_issue_numbers == [42, 99]
    assert saved_epochs[-1] == reviewer_bot.STATUS_PROJECTION_EPOCH

def test_main_schedule_status_projection_epoch_not_advanced_on_label_sync_failure(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_epochs = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "handle_scheduled_check", lambda current: False)
    monkeypatch.setattr(reviewer_bot, "list_open_items_with_status_labels", lambda: [42])
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection exploded")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: saved_epochs.append(current.get("status_projection_epoch")) or True,
    )

    reviewer_bot.main()
    assert all(epoch != reviewer_bot.STATUS_PROJECTION_EPOCH for epoch in saved_epochs)

def test_main_schedule_projection_epoch_repair_relabels_previously_repaired_pr(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 256, create=True)
    assert review is not None
    review["current_reviewer"] = "vccjgust"
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:3821749029",
        "timestamp": "2026-02-18T20:28:12Z",
        "actor": "vccjgust",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["active_head_sha"] = "head-1"
    synced_issue_numbers = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "handle_scheduled_check", lambda current: False)
    monkeypatch.setattr(reviewer_bot, "list_open_items_with_status_labels", lambda: [256])
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True,
    )
    monkeypatch.setattr(reviewer_bot, "save_state", lambda current: True)

    reviewer_bot.main()

    assert synced_issue_numbers == [256]

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

def test_main_workflow_run_bookkeeping_only_reconcile_still_saves_state(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "submitted")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "bob"
    review["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        __import__("json").dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 700,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:11",
                "pr_number": 42,
                "review_id": 11,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "700")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []
    synced_issue_numbers = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/11":
            return {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review:11" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        ) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True,
    )

    reviewer_bot.main()

    assert save_snapshots == [{"reconciled": ["pull_request_review:11"], "gap_present": False}]
    assert synced_issue_numbers == [42]

def test_main_pull_request_synchronize_head_only_mutation_still_saves_state(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_target")
    monkeypatch.setenv("EVENT_ACTION", "synchronize")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("PR_HEAD_SHA", "head-2")
    monkeypatch.setenv("EVENT_CREATED_AT", "2026-03-17T10:00:00Z")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_head_sha"] = "head-1"
    review["contributor_revision"]["seen_keys"] = ["pull_request_sync:42:head-2"]

    save_calls = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data: (None, None),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_calls.append(current["active_reviews"]["42"]["active_head_sha"]) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_calls == ["head-2"]

def test_main_schedule_identical_live_read_failure_does_not_repeat_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="skipped_unavailable",
            failure_kind="server_error",
            reason="pull_request_unavailable",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(dict(current["active_reviews"]["42"]["repair_needed"])) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()
    reviewer_bot.main()

    assert len(save_snapshots) == 1
    assert save_snapshots[0]["kind"] == "live_read_failure"

def test_main_identical_projection_failure_does_not_repeat_repair_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_markers = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot,
        "handle_comment_event",
        lambda current: reviewer_bot.collect_touched_item(42) or False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_markers.append(dict(current["active_reviews"]["42"]["repair_needed"])) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    reviewer_bot.main()
    reviewer_bot.main()

    assert len(save_markers) == 1
    assert save_markers[0]["kind"] == "projection_failure"

def test_main_changed_projection_failure_reason_triggers_new_repair_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_markers = []
    failure_messages = iter(["projection failed", "projection still failed differently"])

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot,
        "handle_comment_event",
        lambda current: reviewer_bot.collect_touched_item(42) or False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_markers.append(dict(current["active_reviews"]["42"]["repair_needed"])) or True,
    )

    def fail_projection(current, issue_numbers):
        raise RuntimeError(next(failure_messages))

    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", fail_projection)

    reviewer_bot.main()
    reviewer_bot.main()

    assert len(save_markers) == 2
    assert save_markers[0]["reason"] == "projection failed"
    assert save_markers[1]["reason"] == "projection still failed differently"

def test_main_workflow_run_deferred_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "created")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 710,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:210",
                "pr_number": 42,
                "comment_id": 210,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": reviewer_bot.comment_routing_module._digest_body("@guidelines-bot /queue"),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "710")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.reconcile_module, "_handle_command", lambda *args, **kwargs: False)

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/210":
            return {
                "body": "@guidelines-bot /queue",
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "issue_comment:210" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        ) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_snapshots == [{"reconciled": ["issue_comment:210"], "gap_present": False}]

def test_main_workflow_run_deferred_comment_contract_drift_persists_gap_update(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "created")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    payload_path = tmp_path / "deferred-command.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 712,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:201",
                "pr_number": 42,
                "comment_id": 201,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": reviewer_bot.comment_routing_module._digest_body("@guidelines-bot /claim"),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "712")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/201":
            return {
                "body": "@guidelines-bot /claim",
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            dict(current["active_reviews"]["42"]["deferred_gaps"]["issue_comment:201"])
        ) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_snapshots[0]["reason"] == "reconcile_failed_closed"

def test_main_workflow_run_deferred_review_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "created")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["pull_request_review_comment:310"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 711,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:310",
                "pr_number": 42,
                "comment_id": 310,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": reviewer_bot.comment_routing_module._digest_body("review comment body"),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "711")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/310":
            return {
                "body": "review comment body",
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
                "created_at": "2026-03-17T10:00:00Z",
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review_comment:310"
                in current["active_reviews"]["42"]["deferred_gaps"],
            }
        ) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_snapshots == [
        {"reconciled": ["pull_request_review_comment:310"], "gap_present": False}
    ]

def test_main_schedule_sweeper_bookkeeping_only_mutation_still_saves_state(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_calls = []

    def fake_sweep(bot, current):
        current["active_reviews"]["42"].setdefault("reconciled_source_events", []).append(
            "pull_request_review:500"
        )
        return True

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", fake_sweep)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_calls.append(
            list(current["active_reviews"]["42"]["reconciled_source_events"])
        ) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_calls == [["pull_request_review:500"]]

def test_main_schedule_reviewer_review_activity_only_repair_still_saves_state(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["reviewer_review"] = {
        "accepted": {
            "semantic_key": "pull_request_review:10",
            "timestamp": "2026-03-17T10:01:00Z",
            "actor": "alice",
            "reviewed_head_sha": "head-1",
            "source_precedence": 1,
            "payload": {},
        },
        "seen_keys": ["pull_request_review:10"],
    }
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"

    save_calls = []

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                200,
                {"state": "open", "head": {"sha": "head-1"}},
                {},
                "ok",
                True,
                None,
                0,
                None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return reviewer_bot.GitHubApiResult(
                200,
                [
                    {
                        "id": 10,
                        "state": "COMMENTED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "alice"},
                    }
                ],
                {},
                "ok",
                True,
                None,
                0,
                None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_calls.append(
            {
                "last_reviewer_activity": current["active_reviews"]["42"]["last_reviewer_activity"],
                "transition_warning_sent": current["active_reviews"]["42"]["transition_warning_sent"],
                "transition_notice_sent_at": current["active_reviews"]["42"]["transition_notice_sent_at"],
            }
        ) or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    reviewer_bot.main()

    assert save_calls == [
        {
            "last_reviewer_activity": "2026-03-17T10:01:00Z",
            "transition_warning_sent": None,
            "transition_notice_sent_at": None,
        }
    ]

def test_classify_event_intent_treats_supported_workflow_run_sources_as_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING

def test_main_records_repair_needed_when_projection_fails(monkeypatch, tmp_path):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "plain text")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        return json.loads(json.dumps(state))

    def fake_save_state(updated_state):
        saved_states.append(json.loads(json.dumps(updated_state)))
        state.clear()
        state.update(json.loads(json.dumps(updated_state)))
        return True

    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "save_state", fake_save_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None})
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current_state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    reviewer_bot.app_module.main(reviewer_bot)
    assert state["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"
    assert len(saved_states) >= 2
