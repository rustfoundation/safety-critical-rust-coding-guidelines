import json
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import (
    lifecycle,
    maintenance,
    maintenance_schedule,
    repair_records,
    review_state,
)
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_scheduled_check_repairs_missing_reviewer_review_state(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    bot.github.get_issue_or_pr_snapshot = lambda issue_number: {"pull_request": {}}
    bot.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
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
        )
    bot.collect_touched_item = lambda issue_number: None
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance_schedule, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, state: [])

    assert maintenance.handle_scheduled_check_result(bot, state).state_changed is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted is not None
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"


def test_scheduled_check_records_live_read_failure_and_continues(monkeypatch):
    state = make_state()
    review_42 = review_state.ensure_review_entry(state, 42, create=True)
    review_43 = review_state.ensure_review_entry(state, 43, create=True)
    assert review_42 is not None and review_43 is not None
    review_42["current_reviewer"] = "alice"
    review_43["current_reviewer"] = "bob"
    overdue_called = []
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    bot.collect_touched_item = lambda issue_number: None
    bot.github.get_issue_or_pr_snapshot = lambda issue_number: {"pull_request": {}}
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, state: overdue_called.append(True) or [])
    monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)

    def fake_head_repair(bot, issue_number, review_data):
        if issue_number == 42:
            return lifecycle.HeadObservationRepairResult(changed=False, outcome="skipped_unavailable", failure_kind="server_error", reason="pull_request_unavailable")
        repair_records.store_repair_marker(review_data, "head_observation_repair", {
            "kind": "live_read_failure",
            "phase": "head_observation_repair",
            "reason": "stale",
            "failure_kind": "server_error",
            "recorded_at": "2026-03-01T00:00:00Z",
        })
        return lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged")

    monkeypatch.setattr(maintenance_schedule, "maybe_record_head_observation_repair", fake_head_repair)

    assert maintenance.handle_scheduled_check_result(bot, state).state_changed is True
    assert overdue_called == [True]
    assert repair_records.load_repair_marker(review_42, "head_observation_repair")["kind"] == "live_read_failure"
    assert repair_records.load_repair_marker(review_42, "head_observation_repair")["failure_kind"] == "server_error"
    assert repair_records.load_repair_marker(review_43, "head_observation_repair") is None


def test_record_maintenance_repair_marker_ignores_recorded_at_for_identical_failure(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    timestamps = iter(["2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"])
    bot = FakeReviewerBotRuntime(monkeypatch)
    monkeypatch.setattr(maintenance_schedule, "_now_iso", lambda bot: next(timestamps))

    first = maintenance_schedule._record_maintenance_repair_marker(
        bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )
    second = maintenance_schedule._record_maintenance_repair_marker(
        bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )

    assert first is True
    assert second is False
    assert repair_records.load_repair_marker(review, "head_observation_repair")["recorded_at"] == "2026-03-01T00:00:00Z"


def test_tracked_pr_repair_pass_collects_touched_items_and_clears_review_repair_marker(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    repair_records.store_repair_marker(review, "review_repair", {
        "kind": "live_read_failure",
        "phase": "review_repair",
        "reason": "stale",
        "failure_kind": None,
        "recorded_at": "2026-03-01T00:00:00Z",
    })
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: True)
    monkeypatch.setattr(
        maintenance_schedule,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"),
    )

    changed, closed_cleanup_removed_items = maintenance_schedule._run_tracked_pr_maintenance(bot, state)

    assert changed is True
    assert closed_cleanup_removed_items == []
    assert bot.drain_touched_items() == [42]
    assert repair_records.load_repair_marker(review, "review_repair") is None


def test_finalize_schedule_result_drains_touched_items_for_projection_followup(monkeypatch):
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.collect_touched_item(42)
    bot.collect_touched_item(99)

    result = maintenance_schedule._finalize_schedule_result(bot, True)

    assert result == maintenance.ScheduleHandlerResult(
        state_changed=True,
        touched_items=[42, 99],
    )
    assert bot.drain_touched_items() == []


def test_manual_dispatch_check_overdue_rejects_unstructured_bool_path(monkeypatch):
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    bot.set_config_value("MANUAL_ACTION", "check-overdue")

    with pytest.raises(RuntimeError, match="handle_manual_dispatch_result"):
        maintenance.handle_manual_dispatch(bot, state)


def test_manual_dispatch_result_routes_check_overdue_through_structured_schedule_result(monkeypatch):
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    bot.set_config_value("MANUAL_ACTION", "check-overdue")
    expected = maintenance.ScheduleHandlerResult(
        state_changed=True,
        touched_items=[42],
        closed_cleanup_removed_items=(42,),
    )
    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", lambda bot, state: expected)

    assert maintenance.handle_manual_dispatch_result(bot, state) == expected


def test_targeted_status_label_repair_policy_and_collection_do_not_broaden(monkeypatch):
    bot = FakeReviewerBotRuntime(monkeypatch)
    state = make_state(epoch="freshness_v15")
    request = maintenance.StatusLabelRepairRequest(
        action="repair-review-status-labels",
        issue_number=264,
        validation_nonce="nonce",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml",
        run_id="1",
        run_attempt="1",
    )
    monkeypatch.setattr(
        maintenance.reviews,
        "list_open_items_with_status_labels",
        lambda bot: (_ for _ in ()).throw(AssertionError("targeted repair broadened")),
    )
    policy = maintenance.derive_manual_dispatch_projection_policy(
        SimpleNamespace(action="repair-review-status-labels", issue_number=264)
    )

    assert policy.allow_epoch_repair_expansion is False
    assert policy.allow_status_label_sync is True
    assert policy.reason == "targeted_status_label_repair"
    assert maintenance.collect_status_label_repair_targets(bot, state, request) == (264,)


def test_broad_status_label_repair_collection_is_explicit(monkeypatch):
    bot = FakeReviewerBotRuntime(monkeypatch)
    request = maintenance.StatusLabelRepairRequest(
        action="repair-review-status-labels",
        issue_number=None,
        validation_nonce="nonce",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml",
        run_id="1",
        run_attempt="1",
    )
    monkeypatch.setattr(maintenance.reviews, "list_open_items_with_status_labels", lambda bot: [42, 264])

    assert maintenance.collect_status_label_repair_targets(bot, make_state(), request) == (42, 264)


def test_issue314_state_health_repair_policy_does_not_broaden_epoch_repair():
    policy = maintenance.derive_manual_dispatch_projection_policy(
        SimpleNamespace(action="repair-issue314-state-health", issue_number=314)
    )

    assert policy.allow_epoch_repair_expansion is False
    assert policy.allow_status_label_sync is True
    assert policy.reason == "issue314_state_health_repair"


def test_status_label_repair_summary_writes_machine_readable_artifact(monkeypatch, tmp_path):
    summary = maintenance.StatusLabelRepairSummary(
        schema_version=1,
        repair_action="repair-review-status-labels",
        issue_number=264,
        issue_numbers=(264,),
        validation_nonce="nonce",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml",
        run_id="1",
        run_attempt="1",
        artifact_name="reviewer-bot-repair-output-1-attempt-1",
        artifact_file="repair-summary.json",
        output_keys=(),
        status_projection_epoch="status_projection_v2",
        before=(),
        after=(),
        labels_added=("status: reviewer reassignment needed",),
        labels_removed=("status: awaiting reviewer response",),
        state_save_attempted=False,
        tracked_state_mutations_attempted=False,
        touched_projection_attempted=False,
        target_collection_mode="issue_scoped",
        result="changed",
    )
    path = tmp_path / "repair-output" / "repair-summary.json"
    monkeypatch.setenv("REPAIR_SUMMARY_PATH", str(path))

    maintenance.emit_status_label_repair_summary(summary)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["repair_action"] == "repair-review-status-labels"
    assert payload["issue_number"] == 264
    assert payload["issue_numbers"] == [264]
    assert payload["target_collection_mode"] == "issue_scoped"
    assert payload["output_keys"] == sorted(payload.keys())


def test_scheduled_check_collects_touched_item_for_warning_diagnostic_mutation(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    bot.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    bot.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    bot.github.post_comment_result = lambda issue_number, body: GitHubApiResult(
        502,
        None,
        {},
        "bad gateway",
        False,
        "server_error",
        1,
        None,
    )
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)
    monkeypatch.setattr(maintenance_schedule, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
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

    assert maintenance.handle_scheduled_check_result(bot, state).touched_items == [42]
    assert repair_records.load_repair_marker(review, "warning_post")["failure_kind"] == "server_error"


def test_scheduled_check_clears_head_observation_repair_marker_after_success(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    repair_records.store_repair_marker(review, "head_observation_repair", {
        "kind": "live_read_failure",
        "phase": "head_observation_repair",
        "reason": "pull_request_unavailable",
        "failure_kind": "server_error",
        "recorded_at": "2026-03-01T00:00:00Z",
    })
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    bot.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance_schedule, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)
    monkeypatch.setattr(maintenance_schedule, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
    monkeypatch.setattr(maintenance_schedule, "check_overdue_reviews", lambda bot, state: [])

    assert maintenance.handle_scheduled_check_result(bot, state).state_changed is True
    assert repair_records.load_repair_marker(review, "head_observation_repair") is None
