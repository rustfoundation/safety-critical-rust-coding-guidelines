from scripts.reviewer_bot_core.reviewer_response_policy import (
    ReviewCycleScope,
    ReviewerResponseDecision,
    apply_reminder_cadence_overlay,
    to_reviewer_response_decision,
)
from scripts.reviewer_bot_lib.overdue import ReminderCadenceDecision


def test_legacy_response_dict_normalizes_to_typed_decision():
    decision = to_reviewer_response_decision(
        {
            "issue_number": 264,
            "current_reviewer": "iglesias",
            "response_state": "awaiting_reviewer_response",
            "current_scope_key": "reviewer=iglesias|head=head-a|cycle=none|anchor=assigned",
            "current_scope_basis": "assigned_at",
            "anchor_timestamp": "2026-04-01T00:00:00Z",
        }
    )

    assert isinstance(decision, ReviewerResponseDecision)
    assert isinstance(decision.scope, ReviewCycleScope)
    assert decision.response_state == "awaiting_reviewer_response"


def test_cadence_overlay_projects_reassignment_needed_once():
    base = to_reviewer_response_decision({"response_state": "awaiting_reviewer_response"})
    cadence = ReminderCadenceDecision(
        issue_number=264,
        reviewer="iglesias",
        scope=base.scope,
        cadence_state="exhausted",
        exhaustion_reason="legacy_duplicate_reminders_exhausted",
        warning_receipt=None,
        transition_receipt=None,
        legacy_duplicate_count=2,
        may_post_warning=False,
        may_post_transition=False,
        must_project_reassignment_needed=True,
    )

    decision = apply_reminder_cadence_overlay(base, cadence)

    assert decision.response_state == "reviewer_reassignment_needed"
    assert decision.suppresses_overdue_reminder is True
    assert decision.reason == "legacy_duplicate_reminders_exhausted"
