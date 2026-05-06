from scripts.reviewer_bot_core.reviewer_review_helpers import (
    build_review_snapshot_record,
    build_reviewer_review_record_from_live_review,
)


def test_review_snapshot_preserves_review_state_and_payload():
    snapshot = build_review_snapshot_record(
        {
            "id": 10,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-04-02T00:00:00Z",
            "commit_id": "head-a",
            "user": {"login": "iglesias"},
        }
    )

    assert snapshot.state == "CHANGES_REQUESTED"
    assert snapshot.to_output()["payload"]["state"] == "CHANGES_REQUESTED"


def test_legacy_review_record_wrapper_uses_snapshot_payload():
    record = build_reviewer_review_record_from_live_review(
        {
            "id": 10,
            "state": "COMMENTED",
            "submitted_at": "2026-04-02T00:00:00Z",
            "commit_id": "head-a",
            "user": {"login": "iglesias"},
        }
    )

    assert record["semantic_key"] == "pull_request_review:10"
    assert record["payload"]["state"] == "COMMENTED"
