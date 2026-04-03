import pytest

from scripts.reviewer_bot_lib import review_state
from tests.fixtures.reconcile_harness import ReconcileHarness, review_submitted_payload
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


def test_workflow_run_review_submission_clears_warning_and_transition_notice_markers(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    harness = ReconcileHarness(
        monkeypatch,
        review_submitted_payload(
            pr_number=42,
            review_id=11,
            source_event_key="pull_request_review:11",
            source_submitted_at="2026-03-17T10:00:00Z",
            source_review_state="COMMENTED",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=500,
            source_run_attempt=2,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-2", author="dana")
    harness.add_review(
        pr_number=42,
        review_id=11,
        submitted_at="2026-03-17T10:00:00Z",
        state="COMMENTED",
        commit_id="head-1",
        author="alice",
    )
    harness.add_reviews_page(
        pr_number=42,
        reviews=[
            {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )

    assert harness.run(state) is True
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None
