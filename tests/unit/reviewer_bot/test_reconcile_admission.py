from scripts.reviewer_bot_core.reconcile_replay_policy import (
    decide_review_dismissed_replay_plan,
)
from scripts.reviewer_bot_lib.reconcile import (
    build_command_replay_receipt,
    build_workflow_run_replay_admission,
)


def test_non_success_observer_admission_disables_replay_and_closeout():
    admission = build_workflow_run_replay_admission(
        source_event_key="pull_request_review:20",
        triggering_conclusion="failure",
        payload_kind="deferred_review_submitted",
        source_authority_status="diagnostic_non_success_identity",
        payload_valid=True,
        identity_present=True,
    )

    assert admission.admission_state == "non_success_diagnostic_only"
    assert admission.replay_allowed is False
    assert admission.mark_reconciled_allowed is False
    assert admission.clear_gap_allowed is False


def test_command_receipt_blocks_closeout_when_state_save_failed():
    receipt = build_command_replay_receipt(
        source_event_key="issue_comment:1",
        issue_number=264,
        command_name="feedback",
        replay_attempted=True,
        command_side_effects_attempted=("comment_command",),
        state_save_required=True,
        state_save_succeeded=False,
        mark_reconciled_allowed=True,
        clear_gap_allowed=True,
    )

    assert receipt.result == "blocked_state_save_failed"


def test_dismissed_review_plan_rebuilds_but_does_not_closeout_without_exact_time():
    plan = decide_review_dismissed_replay_plan(
        source_event_key="pull_request_review_dismissed:20",
        dismissal_timestamp=None,
        dismissal_exact=False,
        live_pr_readable=True,
    )

    assert plan.record_channel_event is False
    assert plan.rebuild_live_approval is True
    assert plan.mark_reconciled is False
    assert plan.clear_gap is False
