from scripts.reviewer_bot_core.live_review_support import classify_review_freshness
from scripts.reviewer_bot_core.reviewer_review_helpers import (
    build_review_snapshot_record,
)


def test_classify_alternate_current_head_review_as_diagnostic_only():
    snapshot = build_review_snapshot_record(
        {
            "id": 1,
            "state": "APPROVED",
            "submitted_at": "2026-04-02T00:00:00Z",
            "commit_id": "head-a",
            "user": {"login": "plaindocs"},
        }
    )

    result = classify_review_freshness(
        snapshot,
        current_head_sha="head-a",
        cycle_boundary="2026-04-01T00:00:00Z",
        assigned_reviewer="iglesias",
    )

    assert result.classified_scope == "current_head_alternate_reviewer"
    assert result.diagnostic_reason == "alternate_reviewer_diagnostic_only"


def test_classify_stale_head_review_rejects_current_scope():
    snapshot = build_review_snapshot_record(
        {
            "id": 2,
            "state": "COMMENTED",
            "submitted_at": "2026-04-02T00:00:00Z",
            "commit_id": "old-head",
            "user": {"login": "iglesias"},
        }
    )

    result = classify_review_freshness(
        snapshot,
        current_head_sha="new-head",
        cycle_boundary="2026-04-01T00:00:00Z",
        assigned_reviewer="iglesias",
    )

    assert result.classified_scope == "stale_head"
    assert result.is_current_head is False
