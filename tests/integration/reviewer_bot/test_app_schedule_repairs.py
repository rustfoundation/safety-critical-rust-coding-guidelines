import json
import pytest

pytestmark = pytest.mark.integration

from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state

def test_execute_run_schedule_status_projection_epoch_mismatch_triggers_label_repair_sweep(monkeypatch):
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

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert synced_issue_numbers == [42, 99]
    assert saved_epochs[-1] == reviewer_bot.STATUS_PROJECTION_EPOCH

def test_execute_run_schedule_status_projection_epoch_not_advanced_on_label_sync_failure(monkeypatch):
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

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert all(epoch != reviewer_bot.STATUS_PROJECTION_EPOCH for epoch in saved_epochs)

def test_execute_run_records_repair_needed_when_projection_fails(monkeypatch, tmp_path):
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
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current_state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert state["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"
    assert len(saved_states) >= 2

def test_schedule_overdue_check_does_not_repeat_warning_after_stale_review_repair(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "schedule")
    monkeypatch.setenv("EVENT_ACTION", "")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "iglesias"
    review["assigned_at"] = "2026-02-26T04:58:03Z"
    review["active_cycle_started_at"] = "2026-02-26T04:58:03Z"
    review["last_reviewer_activity"] = "2026-03-18T01:09:05Z"
    review["transition_warning_sent"] = "2026-04-01T12:12:04Z"

    saved_warning_values = []
    posted_comments = []

    def fake_load_state(*args, **kwargs):
        return state

    def fake_sweep(bot, current):
        bot.reviews_module.record_reviewer_activity(
            current["active_reviews"]["42"],
            "2026-03-18T01:09:05Z",
        )
        return False

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", fake_sweep)
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
        reviewer_bot.reviews_module,
        "compute_reviewer_response_state",
        lambda bot, issue_number, review_data, **kwargs: {
            "state": "awaiting_reviewer_response",
            "reason": "review_head_stale",
            "anchor_timestamp": "2026-03-18T12:09:36Z",
        },
    )
    monkeypatch.setattr(
        reviewer_bot,
        "post_comment",
        lambda issue_number, body: posted_comments.append((issue_number, body)) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: saved_warning_values.append(current["active_reviews"]["42"]["transition_warning_sent"])
        or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: False)

    first = reviewer_bot.execute_run(reviewer_bot.build_event_context())
    second = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert posted_comments == []
    assert review["transition_warning_sent"] == "2026-04-01T12:12:04Z"
    assert saved_warning_values == []
