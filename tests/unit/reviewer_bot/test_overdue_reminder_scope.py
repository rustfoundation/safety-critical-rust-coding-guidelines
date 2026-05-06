from scripts.reviewer_bot_core.reviewer_response_policy import (
    ReviewCycleScope,
    ReviewerResponseDecision,
)
from scripts.reviewer_bot_lib.overdue import (
    build_reminder_delivery_persistence_result,
    derive_reminder_cadence_decision,
    derive_reminder_scope_receipt,
)
from scripts.reviewer_bot_lib.reminder_comments import (
    ReminderCommentRecord,
    ReminderCommentScan,
)


def test_state_warning_field_blocks_without_scope_receipt_authority():
    receipt = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state={"transition_warning_sent": "2026-04-01T00:00:00Z"},
    )

    assert receipt.receipt_kind == "none"
    assert receipt.source == "blocked"
    assert receipt.status == "unavailable"
    assert receipt.created_at == "2026-04-01T00:00:00Z"
    assert receipt.scope_key == "scope-a"
    assert receipt.reason == "scope_unbound_legacy_field"


def test_state_delivery_receipt_requires_matching_scope_identity():
    persisted_state = {
        "sidecars": {
            "reminder_delivery_receipts": {
                "warning:other": {
                    "receipt_kind": "warning",
                    "reviewer": "other",
                    "head_sha": "head-a",
                    "cycle_key": "cycle-a",
                    "scope_key": "scope-a",
                    "comment_id": 123,
                    "comment_created_at": "2026-04-01T00:00:00Z",
                },
                "warning:matching": {
                    "receipt_kind": "warning",
                    "reviewer": "iglesias",
                    "head_sha": "head-a",
                    "cycle_key": "cycle-a",
                    "scope_key": "scope-a",
                    "comment_id": 124,
                    "comment_created_at": "2026-04-02T00:00:00Z",
                },
            }
        }
    }

    receipt = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state=persisted_state,
    )

    assert receipt.comment_id == 124
    assert receipt.source == "state"


def test_single_ambiguous_legacy_scan_blocks_posting_instead_of_reusing_scope():
    record = ReminderCommentRecord(
        comment_id=123,
        author_login="github-actions[bot]",
        created_at="2026-04-01T00:00:00Z",
        body_first_line="Review reminder",
        matched_shape="legacy_actions_warning_or_reminder",
        url=None,
    )
    scan = ReminderCommentScan(
        records=(record,),
        baseline_count=1,
        baseline_latest_created_at="2026-04-01T00:00:00Z",
        scan_status="pass",
    )
    receipt = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state={},
        scanned_comments=scan.records,
    )
    response = ReviewerResponseDecision(
        response_state="awaiting_reviewer_response",
        reason="assigned",
        suppression_reason=None,
        scope=ReviewCycleScope(264, "iglesias", "head-a", "cycle-a", "scope-a", "active_head", "2026-03-01T00:00:00Z"),
        current_head_sha="head-a",
        anchor_timestamp="2026-03-01T00:00:00Z",
        reviewer_authority_outcome="tracked_reviewer_confirmed",
        latest_reviewer_activity_kind=None,
        latest_reviewer_activity_timestamp=None,
        latest_contributor_handoff_timestamp=None,
        suppresses_overdue_reminder=False,
        suppresses_reassignment_followup=False,
        completion_state="not_completed",
        write_approval_authority=None,
    )

    cadence = derive_reminder_cadence_decision(
        response,
        receipt=receipt,
        reminder_scan=scan,
        now="2026-05-01T00:00:00Z",
        review_deadline_days=7,
        transition_period_days=7,
    )

    assert receipt.source == "blocked"
    assert receipt.reason == "ambiguous_legacy_reminder_scan"
    assert cadence.cadence_state == "blocked"
    assert cadence.may_post_warning is False
    assert cadence.may_post_transition is False


def test_posted_comment_save_failure_requires_live_receipt_recovery():
    recovered = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state={
            "sidecars": {
                "reminder_delivery_receipts": {
                    "warning:scope-a:123": {
                        "receipt_kind": "warning",
                        "reviewer": "iglesias",
                        "head_sha": "head-a",
                        "cycle_key": "cycle-a",
                        "scope_key": "scope-a",
                        "comment_id": 123,
                        "comment_created_at": "2026-04-01T00:00:00Z",
                    }
                }
            }
        },
    )

    result = build_reminder_delivery_persistence_result(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        receipt_kind="warning",
        comment_posted=True,
        comment_id=123,
        comment_created_at="2026-04-01T00:00:00Z",
        state_save_attempted=True,
        state_save_succeeded=False,
        recovered_receipt=recovered,
    )

    assert result.result == "posted_save_failed_recoverable"
    assert result.recovery_required is True
