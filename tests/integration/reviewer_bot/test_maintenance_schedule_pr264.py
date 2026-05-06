from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.reviewer_bot_lib import maintenance_schedule, repair_records, reviews
from scripts.reviewer_bot_lib import overdue as overdue_lib
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_builders import accept_reviewer_review
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_scheduled_pr264_legacy_duplicate_no_ping_path_preserves_state(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    review["active_head_sha"] = "head-live"
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:77",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
    )
    sidecars = review.setdefault("sidecars", {})
    sidecars["reminder_delivery_receipts"] = {
        "legacy:264:9002": {
            "issue_number": 264,
            "reviewer": "iglesias",
            "head_sha": "head-live",
            "cycle_key": "2026-02-10T17:20:07Z",
            "scope_key": "reviewer=iglesias|head=head-live|cycle=2026-02-10T17:20:07Z|anchor=2026-02-10T17:20:07Z",
            "receipt_kind": "legacy_warning_or_reminder",
            "comment_id": 9002,
            "comment_created_at": "2026-04-14T00:44:23Z",
            "state_save_attempted": False,
            "state_save_succeeded": False,
            "result": "not_posted_existing_receipt",
        }
    }
    sidecars["deferred_gaps"] = {
        "pull_request_review:77": {
            "source_event_key": "pull_request_review:77",
            "workflow_name": "Reviewer Bot PR Review Submitted Observer",
            "failure_kind": "diagnostic_only",
            "diagnostic_summary": "retained diagnostic gap",
        }
    }
    sidecars["observer_discovery_watermarks"] = {
        "review_submitted": {
            "workflow_name": "Reviewer Bot PR Review Submitted Observer",
            "last_scan_completed_at": "2026-04-14T01:00:00Z",
            "diagnostics_retained": True,
        }
    }
    sidecars["reconciled_source_events"] = {
        "issue_comment:210": {
            "source_event_key": "issue_comment:210",
            "issue_number": 264,
            "source_event_action": "created",
            "replay_decision": "pass_diagnostic_only",
            "mark_reconciled": False,
            "clear_gap": False,
            "reconciled_at": None,
            "diagnostic_reason": "plain_lgtm_comment_is_diagnostic_only",
        }
    }
    repair_records.store_repair_marker(
        review,
        "status_label_projection",
        {
            "kind": "projection_failure",
            "issue_number": 264,
            "repair_action": "repair-review-status-labels",
            "target_collection_mode": "issue_scoped",
            "status_projection_epoch": "status_projection_v2",
            "before_status_labels": ["status: awaiting reviewer response"],
            "desired_status_labels": ["status: reviewer reassignment needed"],
            "labels_added": ["status: reviewer reassignment needed"],
            "labels_removed": ["status: awaiting reviewer response"],
            "repaired_at": None,
            "result": "blocked",
        },
    )
    repair_records.repair_markers(review)
    before_state = deepcopy(state)

    comments = [
        {
            "id": 210,
            "user": {"login": "iglesias"},
            "created_at": "2026-04-13T23:23:25Z",
            "body": "LGTM",
        },
        {
            "id": 9001,
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-04-13T00:44:23Z",
            "body": "**Review Reminder**\n\ntransition period",
        },
        {
            "id": 9002,
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-04-14T00:44:23Z",
            "body": "**Review Reminder**\n\ntransition period",
        },
    ]
    pr_payload = {
        **pull_request_payload(264, head_sha="head-live", author="manhatsu"),
        "requested_reviewers": [],
        "assignees": [],
        "labels": [{"name": "status: awaiting reviewer response"}],
    }
    routes = (
        RouteGitHubApi()
        .add_request(
            "GET",
            "issues/264",
            status_code=200,
            payload={
                "number": 264,
                "state": "open",
                "pull_request": {},
                "labels": [{"name": "status: awaiting reviewer response"}],
            },
        )
        .add_request("GET", "pulls/264", status_code=200, payload=pr_payload)
        .add_pull_request_reviews(
            264,
            [
                review_payload(
                    501,
                    state="APPROVED",
                    submitted_at="2026-03-18T12:10:42Z",
                    commit_id="head-live",
                    author="plaindocs",
                )
            ],
        )
        .add_request("GET", "issues/264/comments?per_page=100&page=1", status_code=200, payload=comments)
    )
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.ACTIVE_LEASE_CONTEXT = object()
    bot.github.stub(routes)
    bot.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    bot.github.post_comment_result = lambda issue_number, body: (_ for _ in ()).throw(
        AssertionError("scheduled PR264 no-ping path must not post reviewer-facing comments")
    )
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(
        maintenance_schedule,
        "collect_status_projection_repair_items",
        lambda bot, current: (_ for _ in ()).throw(AssertionError("scheduled PR264 no-ping path broadened repair collection")),
    )
    monkeypatch.setattr(
        reviews,
        "list_open_items_with_status_labels",
        lambda bot: (_ for _ in ()).throw(AssertionError("scheduled PR264 no-ping path reached broad status-label collection")),
    )
    reminder_decisions = []
    original_decide = overdue_lib.decide_overdue_reminder

    def record_reminder_decision(*args, **kwargs):
        decision = original_decide(*args, **kwargs)
        reminder_decisions.append(decision)
        return decision

    monkeypatch.setattr(overdue_lib, "decide_overdue_reminder", record_reminder_decision)

    result = maintenance_schedule.handle_scheduled_check_result(bot, state)

    assert result.state_changed is False
    assert result.touched_items == []
    assert result.closed_cleanup_removed_items == ()
    assert state == before_state
    assert reminder_decisions
    assert reminder_decisions[-1].action == "none"
    assert reminder_decisions[-1].reason == "legacy_duplicate_reminders_exhausted"
    assert all(call.method == "GET" for call in routes.request_calls)
    assert not any("labels" in call.endpoint for call in routes.request_calls)
