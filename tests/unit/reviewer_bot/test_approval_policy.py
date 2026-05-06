from scripts.reviewer_bot_core.approval_policy import (
    derive_completion_authority_decision,
    derive_write_approval_authority_decision,
)
from scripts.reviewer_bot_core.live_review_support import classify_review_freshness
from scripts.reviewer_bot_core.reviewer_review_helpers import (
    build_review_snapshot_record,
)


def _classification(state="APPROVED", author="iglesias"):
    return classify_review_freshness(
        build_review_snapshot_record(
            {
                "id": 10,
                "state": state,
                "submitted_at": "2026-04-02T00:00:00Z",
                "commit_id": "head-a",
                "user": {"login": author},
            }
        ),
        current_head_sha="head-a",
        cycle_boundary="2026-04-01T00:00:00Z",
        assigned_reviewer="iglesias",
    )


def test_completion_authority_uses_review_timestamp_not_runtime_clock():
    decision = derive_completion_authority_decision(
        issue_number=264,
        tracked_reviewer="iglesias",
        head_sha="head-a",
        review_classification=_classification(),
        non_assigned_review_diagnostic=False,
    )

    assert decision.can_set_review_completed_at is True
    assert decision.completion_timestamp == "2026-04-02T00:00:00Z"
    assert decision.timestamp_source == "current_head_tracked_reviewer_review"


def test_assigned_approval_without_visible_write_authority_projects_awaiting_write_approval():
    assigned = _classification()
    decision = derive_write_approval_authority_decision(
        issue_number=264,
        head_sha="head-a",
        assigned_reviewer="iglesias",
        assigned_review_classification=assigned,
        visible_review_classifications=(assigned,),
        permission_evidence={"iglesias": "denied"},
        dismissal_evidence=None,
    )

    assert decision.response_state == "awaiting_write_approval"
    assert decision.write_approval_state == "visibly_missing_write_approval"
