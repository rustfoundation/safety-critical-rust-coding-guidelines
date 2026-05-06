from scripts.reviewer_bot_core.reviewer_response_policy import (
    to_reviewer_response_decision,
)
from scripts.reviewer_bot_lib.overdue import (
    decide_overdue_reminder,
    derive_reminder_cadence_decision,
)
from scripts.reviewer_bot_lib.reminder_comments import (
    ReminderCommentRecord,
    ReminderCommentScan,
)


def test_duplicate_legacy_reminders_exhaust_cadence_without_posting():
    response = to_reviewer_response_decision({"response_state": "awaiting_reviewer_response"})
    scan = ReminderCommentScan(
        records=(
            ReminderCommentRecord(1, "github-actions[bot]", "2026-04-01T00:00:00Z", "Review Reminder", "legacy_unmarked_warning", None),
            ReminderCommentRecord(2, "github-actions[bot]", "2026-04-02T00:00:00Z", "Review Reminder", "legacy_unmarked_warning", None),
        ),
        baseline_count=2,
        baseline_latest_created_at="2026-04-02T00:00:00Z",
        scan_status="pass",
    )

    cadence = derive_reminder_cadence_decision(
        response,
        receipt=None,
        reminder_scan=scan,
        now=object(),
        review_deadline_days=7,
        transition_period_days=3,
    )
    decision = decide_overdue_reminder(response, cadence=cadence, now=object(), review_deadline_days=7, transition_period_days=3)

    assert cadence.must_project_reassignment_needed is True
    assert decision.action == "none"
    assert decision.reason == "legacy_duplicate_reminders_exhausted"
