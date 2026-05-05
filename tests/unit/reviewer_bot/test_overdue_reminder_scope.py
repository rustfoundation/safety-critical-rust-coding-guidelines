from scripts.reviewer_bot_lib.overdue import (
    build_reminder_delivery_persistence_result,
    derive_reminder_scope_receipt,
)


def test_state_warning_field_becomes_scope_receipt_not_global_authority():
    receipt = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state={"transition_warning_sent": "2026-04-01T00:00:00Z"},
    )

    assert receipt.receipt_kind == "warning"
    assert receipt.created_at == "2026-04-01T00:00:00Z"
    assert receipt.scope_key == "scope-a"


def test_posted_comment_save_failure_requires_live_receipt_recovery():
    recovered = derive_reminder_scope_receipt(
        issue_number=264,
        reviewer="iglesias",
        head_sha="head-a",
        cycle_key="cycle-a",
        scope_key="scope-a",
        persisted_state={"transition_warning_sent": "2026-04-01T00:00:00Z"},
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
