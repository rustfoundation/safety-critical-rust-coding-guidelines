from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_core.comment_freshness_policy import (
    build_comment_freshness_event,
    decide_comment_freshness_event,
)
from scripts.reviewer_bot_core.reviewer_response_policy import (
    apply_reminder_cadence_overlay,
    to_reviewer_response_decision,
)
from scripts.reviewer_bot_lib.overdue import ReminderCadenceDecision
from scripts.reviewer_bot_lib.reminder_comments import (
    ReminderCommentRecord,
    ReminderCommentScan,
)

pytestmark = pytest.mark.integration


def test_pr264_plain_lgtm_replay_is_diagnostic_and_cadence_exhaustion_projects_reassignment_needed():
    review_data = {
        "current_reviewer": "iglesias",
        "transition_warning_sent": "2026-04-14T00:44:23Z",
        "review_completed_at": None,
    }
    request = SimpleNamespace(
        issue_number=264,
        is_pull_request=True,
        issue_author="manhatsu",
        comment_id=112233,
        comment_author="iglesias",
        comment_created_at="2026-04-13T23:23:25Z",
        comment_source_event_key="issue_comment:112233",
        comment_source_kind="issue_comment",
        reviewed_head_sha=None,
    )

    freshness = decide_comment_freshness_event(
        build_comment_freshness_event(review_data, request),
        current_head_sha="7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
    )

    assert freshness.kind == "diagnostic_only"
    assert freshness.update_reviewer_activity is False

    base_response = to_reviewer_response_decision(
        {
            "issue_number": 264,
            "current_reviewer": "iglesias",
            "response_state": "awaiting_reviewer_response",
            "reason": "review_head_stale",
        }
    )
    reminder_scan = ReminderCommentScan(
        records=(
            ReminderCommentRecord(9001, "github-actions[bot]", "2026-04-10T00:00:00Z", "Review Reminder", "legacy_unmarked_warning", None),
            ReminderCommentRecord(9002, "github-actions[bot]", "2026-04-14T00:44:23Z", "Review Reminder", "legacy_unmarked_warning", None),
        ),
        baseline_count=2,
        baseline_latest_created_at="2026-04-14T00:44:23Z",
        scan_status="pass",
    )
    cadence = ReminderCadenceDecision(
        issue_number=264,
        reviewer="iglesias",
        scope=base_response.scope,
        cadence_state="exhausted",
        exhaustion_reason="legacy_duplicate_reminders_exhausted",
        warning_receipt=None,
        transition_receipt=None,
        legacy_duplicate_count=reminder_scan.baseline_count,
        may_post_warning=False,
        may_post_transition=False,
        must_project_reassignment_needed=True,
    )

    effective_response = apply_reminder_cadence_overlay(base_response, cadence)

    assert effective_response.response_state == "reviewer_reassignment_needed"
    assert effective_response.reason == "legacy_duplicate_reminders_exhausted"
    assert effective_response.suppresses_overdue_reminder is True
