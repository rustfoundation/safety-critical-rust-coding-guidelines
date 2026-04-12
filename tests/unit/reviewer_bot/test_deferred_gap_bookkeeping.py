from scripts.reviewer_bot_lib import deferred_gap_bookkeeping, review_state
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_ensure_source_event_key_creates_and_updates_deferred_gap_payloads(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None

    deferred_gap_bookkeeping._ensure_source_event_key(review, "issue_comment:210", {"reason": "artifact_missing"})
    deferred_gap_bookkeeping._ensure_source_event_key(review, "issue_comment:210", {"reason": "reconcile_failed_closed"})

    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"] == {
        "source_event_key": "issue_comment:210",
        "reason": "reconcile_failed_closed",
    }


def test_bookkeeping_owner_marks_clears_and_tracks_reconciled_source_events(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    assert deferred_gap_bookkeeping._clear_source_event_key(review, "issue_comment:210") is True
    assert deferred_gap_bookkeeping._mark_reconciled_source_event(review, "issue_comment:210") is True
    assert deferred_gap_bookkeeping._mark_reconciled_source_event(review, "issue_comment:210") is False
    assert deferred_gap_bookkeeping._was_reconciled_source_event(review, "issue_comment:210") is True
    assert review["sidecars"]["deferred_gaps"] == {}
    assert review["sidecars"]["reconciled_source_events"] == {
        "issue_comment:210": {
            "source_event_key": "issue_comment:210",
            "reconciled_at": None,
        }
    }


def test_update_deferred_gap_preserves_first_noted_and_refreshes_last_checked(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {
        "first_noted_at": "2026-03-17T09:00:00+00:00",
        "last_checked_at": "2026-03-17T09:00:00+00:00",
    }
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    changed = deferred_gap_bookkeeping._update_deferred_gap(
        runtime,
        review,
        {
            "source_event_key": "issue_comment:210",
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "pr_number": 42,
            "source_created_at": "2026-03-17T10:00:00Z",
            "source_run_id": 700,
            "source_run_attempt": 1,
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "source_artifact_name": "reviewer-bot-comment-context-700-attempt-1",
        },
        "awaiting_observer_run",
        "Trusted sweeper diagnostics for issue_comment:210.",
        failure_kind="server_error",
    )

    assert changed is True
    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"]["first_noted_at"] == "2026-03-17T09:00:00+00:00"
    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"]["last_checked_at"] == "2026-03-18T00:00:00+00:00"
    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"]["failure_kind"] == "server_error"
