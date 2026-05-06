import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import (
    app,
    deferred_gap_bookkeeping,
    lifecycle,
    maintenance,
    maintenance_schedule,
    review_state,
)
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration

def test_execute_run_schedule_sweeper_bookkeeping_only_mutation_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_calls = []

    def fake_sweep(bot, current):
        deferred_gap_bookkeeping.mark_reconciled_source_event(
            current["active_reviews"]["42"],
            "pull_request_review:500",
            reconciled_at="2026-03-18T00:00:00+00:00",
        )
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))

    def fake_schedule_result(bot, current):
        fake_sweep(bot, current)
        return maintenance.ScheduleHandlerResult(True, [])

    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(
        lambda current: save_calls.append(
            list(current["active_reviews"]["42"]["sidecars"]["reconciled_source_events"])
        ) or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_calls == [["pull_request_review:500"]]

def test_execute_run_schedule_reviewer_review_activity_only_repair_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
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
            return GitHubApiResult(
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
            return GitHubApiResult(
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

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))

    def fake_schedule_result(bot, current):
        current_review = current["active_reviews"]["42"]
        current_review["last_reviewer_activity"] = "2026-03-17T10:01:00Z"
        current_review["transition_warning_sent"] = None
        current_review["transition_notice_sent_at"] = None
        return maintenance.ScheduleHandlerResult(True, [])

    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(
        lambda current: save_calls.append(
            {
                "last_reviewer_activity": current["active_reviews"]["42"]["last_reviewer_activity"],
                "transition_warning_sent": current["active_reviews"]["42"]["transition_warning_sent"],
                "transition_notice_sent_at": current["active_reviews"]["42"]["transition_notice_sent_at"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_calls == [
        {
            "last_reviewer_activity": "2026-03-17T10:01:00Z",
            "transition_warning_sent": None,
            "transition_notice_sent_at": None,
        }
    ]


def test_m2_schedule_handler_exposes_typed_result_shape():
    assert maintenance.ScheduleHandlerResult is maintenance_schedule.ScheduleHandlerResult

    fields = maintenance_schedule.ScheduleHandlerResult.__dataclass_fields__
    assert list(fields) == ["state_changed", "touched_items", "closed_cleanup_removed_items"]


def test_execute_run_schedule_warning_diagnostic_mutation_projects_touched_item(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_states = []
    synced = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    harness.runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    harness.runtime.github.post_comment_result = lambda issue_number, body: GitHubApiResult(
        502,
        None,
        {},
        "bad gateway",
        False,
        "server_error",
        1,
        None,
    )
    harness.stub_save_state(lambda current: saved_states.append(current.copy()) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)
    monkeypatch.setattr(
        maintenance_schedule,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"),
    )
    monkeypatch.setattr(
        maintenance_schedule,
        "check_overdue_reviews",
        lambda bot, state: [
            {
                "issue_number": 42,
                "reviewer": "alice",
                "days_overdue": 1,
                "days_since_warning": 0,
                "needs_warning": True,
                "needs_transition": False,
                "anchor_reason": None,
                "anchor_timestamp": "2026-03-17T10:00:00Z",
            }
        ],
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert saved_states
    assert synced == [[42]]


def test_execute_run_schedule_warning_post_save_failure_recovers_from_live_comment(monkeypatch):
    original_state = make_state()
    review = review_state.ensure_review_entry(original_state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-17T10:00:00Z"
    review["active_cycle_started_at"] = "2026-03-17T10:00:00Z"
    issue_snapshot = {"number": 42, "state": "open", "pull_request": {}, "labels": []}
    pull_request = {
        "number": 42,
        "state": "open",
        "head": {"sha": "head-1"},
        "requested_reviewers": [],
        "user": {"login": "dana"},
    }
    posted_comment = {}

    def configure_common(harness, state, comments):
        harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
        harness.runtime.datetime = SimpleNamespace(
            now=lambda tz=None: datetime(2026, 4, 2, tzinfo=tz or timezone.utc)
        )
        harness.stub_lock(acquire=lambda: None, release=lambda: True)
        harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
        harness.stub_pass_until(lambda current: (current, []))
        harness.stub_sync_members(lambda current: (current, []))
        harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot
        harness.runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: GitHubApiResult(
            200,
            issue_snapshot,
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
        harness.runtime.github.get_issue_assignees = lambda issue_number: []
        harness.runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: GitHubApiResult(
            200,
            list(comments),
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
        harness.runtime.github.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request if endpoint == "pulls/42" else [],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
        monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, current: False)
        monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)
        monkeypatch.setattr(
            maintenance_schedule,
            "maybe_record_head_observation_repair",
            lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"),
        )

    first_state = copy.deepcopy(original_state)
    first = AppHarness(monkeypatch)
    configure_common(first, first_state, [])

    def post_warning(issue_number, body):
        posted_comment.update(
            {
                "id": 901,
                "user": {"login": "github-actions[bot]"},
                "created_at": "2026-04-01T00:00:00Z",
                "body": body,
            }
        )
        return GitHubApiResult(201, {"id": 901, "created_at": "2026-04-01T00:00:00Z"}, {}, "created", True, None, 0, None)

    first.runtime.github.post_comment_result = post_warning
    first.stub_save_state(lambda current: False)
    first.stub_sync_status_labels(lambda current, issue_numbers: pytest.fail("failed save must not project labels"))

    first_result = first.run_execute()

    assert first_result.exit_code == 1
    assert posted_comment["body"].startswith("<!-- reviewer-bot:transition-warning:v1 ")

    recovered_state = copy.deepcopy(original_state)
    saved_states = []
    synced = []
    second = AppHarness(monkeypatch)
    configure_common(second, recovered_state, [posted_comment])
    second.runtime.github.post_comment_result = lambda issue_number, body: pytest.fail("live warning receipt should suppress duplicate post")
    second.stub_save_state(lambda current: saved_states.append(copy.deepcopy(current)) or True)
    second.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)

    second_result = second.run_execute()

    assert second_result.exit_code == 0
    assert saved_states
    recovered_review = saved_states[0]["active_reviews"]["42"]
    assert recovered_review["transition_warning_sent"] == "2026-04-01T00:00:00Z"
    receipts = recovered_review["sidecars"]["reminder_delivery_receipts"]
    assert len(receipts) == 1
    receipt = next(iter(receipts.values()))
    assert receipt["result"] == "not_posted_existing_receipt"
    assert receipt["recovered_receipt"]["source"] == "comment_scan"
    assert synced == [[42]]


def test_execute_run_schedule_isolated_from_reviewer_board_configuration(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="", REVIEWER_BOARD_ENABLED="true")
    state = make_state()
    saved = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    monkeypatch.setattr(
        maintenance,
        "handle_scheduled_check_result",
        lambda bot, current: maintenance.ScheduleHandlerResult(True, []),
    )
    harness.runtime.github_graphql = lambda *args, **kwargs: pytest.fail("schedule path must not touch reviewer board GraphQL")
    harness.stub_save_state(lambda current: saved.append(copy.deepcopy(current)) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert saved


def test_execute_run_schedule_removes_closed_pr_rows_through_lifecycle_owner(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_active_reviews = []
    synced = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {
        "number": issue_number,
        "state": "closed",
        "pull_request": {},
        "labels": [],
    }
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, current: [])
    harness.stub_save_state(lambda current: saved_active_reviews.append(dict(current["active_reviews"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert saved_active_reviews == [{}]
    assert synced == [[42]]


def test_execute_run_schedule_removes_closed_rows_without_reviewer(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = None
    saved_active_reviews = []
    synced = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {
        "number": issue_number,
        "state": "closed",
        "labels": [],
    }
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, current: [])
    harness.stub_save_state(lambda current: saved_active_reviews.append(dict(current["active_reviews"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert saved_active_reviews == [{}]
    assert synced == [[42]]


def test_execute_run_schedule_empty_active_reviews_guard_requires_closed_cleanup_rows(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    save_called = {"value": False}

    def fake_schedule_result(bot, current):
        current["active_reviews"].clear()
        return maintenance.ScheduleHandlerResult(True, [42])

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert save_called["value"] is False


def test_execute_run_schedule_closed_cleanup_empty_save_ignores_projection_repair_touched_items(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    state["status_projection_epoch"] = None
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_active_reviews = []
    synced = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {
        "number": issue_number,
        "state": "closed",
        "pull_request": {},
        "labels": [],
    }
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, current: [])
    monkeypatch.setattr(app, "collect_status_projection_repair_items", lambda bot, current: [99])
    harness.stub_save_state(lambda current: saved_active_reviews.append(dict(current["active_reviews"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert saved_active_reviews == [{}, {}]
    assert synced == [[42, 99]]


def test_execute_run_schedule_empty_active_reviews_guard_blocks_partial_cleanup_full_drop(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review_42 = review_state.ensure_review_entry(state, 42, create=True)
    review_99 = review_state.ensure_review_entry(state, 99, create=True)
    assert review_42 is not None
    assert review_99 is not None
    review_42["current_reviewer"] = "alice"
    review_99["current_reviewer"] = "bob"
    save_called = {"value": False}

    def fake_schedule_result(bot, current):
        current["active_reviews"].clear()
        return maintenance.ScheduleHandlerResult(
            True,
            [42, 99],
            closed_cleanup_removed_items=(42,),
        )

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert save_called["value"] is False


def test_execute_run_manual_check_overdue_uses_closed_cleanup_rows_for_empty_guard(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="workflow_dispatch", EVENT_ACTION="", MANUAL_ACTION="check-overdue")
    state = make_state()
    state["status_projection_epoch"] = None
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    saved_active_reviews = []
    synced = []

    def fake_schedule_result(current):
        current["active_reviews"].clear()
        return maintenance.ScheduleHandlerResult(
            True,
            [42],
            closed_cleanup_removed_items=(42,),
        )

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler("handle_manual_dispatch_result", fake_schedule_result)
    monkeypatch.setattr(app, "collect_status_projection_repair_items", lambda bot, current: [99])
    harness.stub_save_state(lambda current: saved_active_reviews.append(dict(current["active_reviews"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced.append(list(issue_numbers)) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert saved_active_reviews == [{}, {}]
    assert synced == [[42, 99]]


def test_execute_run_manual_check_overdue_empty_guard_blocks_unowned_full_drop(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="workflow_dispatch", EVENT_ACTION="", MANUAL_ACTION="check-overdue")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    save_called = {"value": False}

    def fake_schedule_result(current):
        current["active_reviews"].clear()
        return maintenance.ScheduleHandlerResult(True, [42])

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler("handle_manual_dispatch_result", fake_schedule_result)
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert save_called["value"] is False
