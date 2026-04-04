import json

import pytest

pytestmark = pytest.mark.integration

from scripts.reviewer_bot_lib import maintenance, review_state
from scripts.reviewer_bot_lib.config import STATUS_PROJECTION_EPOCH
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state


def test_execute_run_schedule_status_projection_epoch_mismatch_triggers_label_repair_sweep(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    synced_issue_numbers = []
    saved_epochs = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler("handle_scheduled_check", lambda current: False)
    harness.runtime.list_open_items_with_status_labels = lambda: [99]
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True)
    harness.stub_save_state(lambda current: saved_epochs.append(current.get("status_projection_epoch")) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert synced_issue_numbers == [42, 99]
    assert saved_epochs[-1] == STATUS_PROJECTION_EPOCH

def test_execute_run_schedule_status_projection_epoch_not_advanced_on_label_sync_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_epochs = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler("handle_scheduled_check", lambda current: False)
    harness.runtime.list_open_items_with_status_labels = lambda: [42]
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection exploded")))
    harness.stub_save_state(lambda current: saved_epochs.append(current.get("status_projection_epoch")) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert all(epoch != STATUS_PROJECTION_EPOCH for epoch in saved_epochs)

def test_execute_run_records_repair_needed_when_projection_fails(monkeypatch, tmp_path):
    harness = AppHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        IS_PULL_REQUEST="false",
        ISSUE_NUMBER="42",
        ISSUE_AUTHOR="dana",
        COMMENT_USER_TYPE="User",
        COMMENT_AUTHOR="dana",
        COMMENT_ID="100",
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="plain text",
    )
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        return json.loads(json.dumps(state))

    def fake_save_state(updated_state):
        saved_states.append(json.loads(json.dumps(updated_state)))
        state.clear()
        state.update(json.loads(json.dumps(updated_state)))
        return True

    harness.stub_load_state(fake_load_state)
    harness.stub_save_state(fake_save_state)
    harness.stub_pass_until(lambda current_state: (current_state, []))
    harness.stub_sync_members(lambda current_state: (current_state, []))
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None}
    harness.stub_sync_status_labels(lambda current_state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    result = harness.run_execute()

    assert result.exit_code == 0
    assert state["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"
    assert len(saved_states) >= 2

def test_schedule_overdue_check_does_not_repeat_warning_after_stale_review_repair(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
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
        review_state.record_reviewer_activity(
            current["active_reviews"]["42"],
            "2026-03-18T01:09:05Z",
        )
        return False

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: fake_load_state())
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    monkeypatch.setattr(maintenance, "sweep_deferred_gaps", fake_sweep)
    harness.stub_handler("handle_scheduled_check", lambda current: False)
    harness.runtime.post_comment = lambda issue_number, body: posted_comments.append((issue_number, body)) or True
    harness.stub_save_state(
        lambda current: saved_warning_values.append(current["active_reviews"]["42"]["transition_warning_sent"]) or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: False)

    first = harness.run_execute()
    second = harness.run_execute()

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert posted_comments == []
    assert review["transition_warning_sent"] == "2026-04-01T12:12:04Z"
    assert saved_warning_values == []
