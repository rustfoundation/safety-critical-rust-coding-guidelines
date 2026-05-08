from scripts.reviewer_bot_lib.reminder_comments import (
    diff_reviewer_reminder_scans,
    scan_reviewer_reminder_comments,
)


def test_scan_classifies_legacy_unmarked_warning_with_comment_created_at():
    scan = scan_reviewer_reminder_comments(
        [
            {
                "id": 1,
                "created_at": "2026-04-01T00:00:00Z",
                "body": "⚠️ **Review Reminder**\n\nIf no action is taken within 3 days, transition period applies.",
                "user": {"login": "github-actions[bot]"},
            }
        ]
    )

    assert scan.scan_status == "pass"
    assert scan.records[0].matched_shape == "legacy_unmarked_warning"
    assert scan.records[0].created_at == "2026-04-01T00:00:00Z"


def test_scan_classifies_pr264_legacy_warning_text_without_transition_period_phrase():
    scan = scan_reviewer_reminder_comments(
        [
            {
                "id": 4240517367,
                "created_at": "2026-04-14T00:44:23Z",
                "body": "⚠️ **Review Reminder**\n\n"
                "Hey @iglesias, it's been more than 14 days since you were assigned to review this.\n\n"
                "If no action is taken within 14 days, you may be transitioned from Producer to Observer status.",
                "user": {"login": "github-actions[bot]"},
            }
        ]
    )

    assert scan.scan_status == "pass"
    assert scan.records[0].matched_shape == "legacy_unmarked_warning"
    assert scan.records[0].created_at == "2026-04-14T00:44:23Z"


def test_diff_uses_comment_identity_not_latest_timestamp_only():
    before = scan_reviewer_reminder_comments([])
    after = scan_reviewer_reminder_comments(
        [
            {
                "id": 1,
                "created_at": "2026-04-01T00:00:00Z",
                "body": "🔔 **Transition Period Ended**",
                "user": {"login": "github-actions[bot]"},
            }
        ]
    )

    diff = diff_reviewer_reminder_scans(before, after)

    assert diff.diff_status == "pass"
    assert len(diff.new_records) == 1
