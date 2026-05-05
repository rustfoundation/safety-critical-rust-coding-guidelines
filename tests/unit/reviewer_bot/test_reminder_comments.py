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
