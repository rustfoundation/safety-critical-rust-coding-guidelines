from scripts.reviewer_bot_lib import deferred_gap_bookkeeping, review_state
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_record_deferred_gap_payload_creates_and_updates_payloads(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None

    deferred_gap_bookkeeping.record_deferred_gap_payload(review, "issue_comment:210", {"reason": "artifact_missing"})
    deferred_gap_bookkeeping.record_deferred_gap_payload(review, "issue_comment:210", {"reason": "reconcile_failed_closed"})

    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"] == {
        "source_event_key": "issue_comment:210",
        "reason": "reconcile_failed_closed",
    }


def test_bookkeeping_does_not_expose_raw_sidecar_map_accessors():
    assert hasattr(deferred_gap_bookkeeping, "get_deferred_gaps") is False
    assert hasattr(deferred_gap_bookkeeping, "get_reconciled_source_events") is False
    assert hasattr(deferred_gap_bookkeeping, "get_observer_discovery_watermarks") is False
    assert hasattr(deferred_gap_bookkeeping, "ensure_observer_discovery_watermark") is False


def test_bookkeeping_owner_marks_clears_and_tracks_reconciled_source_events(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    assert deferred_gap_bookkeeping.clear_deferred_gap(review, "issue_comment:210") is True
    assert deferred_gap_bookkeeping.mark_reconciled_source_event(
        review,
        "issue_comment:210",
        reconciled_at="2026-03-18T00:00:00+00:00",
    ) is True
    assert deferred_gap_bookkeeping.mark_reconciled_source_event(
        review,
        "issue_comment:210",
        reconciled_at="2026-03-18T00:00:00+00:00",
    ) is False
    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is True
    assert review["sidecars"]["deferred_gaps"] == {}
    assert review["sidecars"]["reconciled_source_events"] == {
        "issue_comment:210": {
            "source_event_key": "issue_comment:210",
            "reconciled_at": "2026-03-18T00:00:00+00:00",
        }
    }


def test_bookkeeping_owner_creates_non_null_reconciled_at_by_default(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None

    assert deferred_gap_bookkeeping.mark_reconciled_source_event(review, "issue_comment:210") is True

    reconciled_at = review["sidecars"]["reconciled_source_events"]["issue_comment:210"]["reconciled_at"]
    assert isinstance(reconciled_at, str)
    assert reconciled_at
    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is True


def test_bookkeeping_owner_repairs_legacy_null_reconciled_at(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["reconciled_source_events"]["issue_comment:210"] = {
        "source_event_key": "issue_comment:210",
        "reconciled_at": None,
    }

    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is False
    assert deferred_gap_bookkeeping.mark_reconciled_source_event(
        review,
        "issue_comment:210",
        reconciled_at="2026-03-18T00:00:00+00:00",
    ) is True

    assert review["sidecars"]["reconciled_source_events"]["issue_comment:210"] == {
        "source_event_key": "issue_comment:210",
        "reconciled_at": "2026-03-18T00:00:00+00:00",
    }
    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is True


def test_bookkeeping_owner_repairs_legacy_invalid_reconciled_at_values(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["reconciled_source_events"]["issue_comment:210"] = {
        "source_event_key": "issue_comment:999",
        "reconciled_at": "   ",
    }

    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is False
    assert deferred_gap_bookkeeping.mark_reconciled_source_event(
        review,
        "issue_comment:210",
        reconciled_at="2026-03-18T00:00:00+00:00",
    ) is True

    assert review["sidecars"]["reconciled_source_events"]["issue_comment:210"] == {
        "source_event_key": "issue_comment:210",
        "reconciled_at": "2026-03-18T00:00:00+00:00",
    }
    assert deferred_gap_bookkeeping.was_reconciled_source_event(review, "issue_comment:210") is True


def test_bookkeeping_owner_updates_deferred_gap_fields_without_recreating_missing_gap(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    assert deferred_gap_bookkeeping.update_deferred_gap_fields(
        review,
        "issue_comment:210",
        {"full_scan_complete": True},
    ) is True
    assert deferred_gap_bookkeeping.update_deferred_gap_fields(
        review,
        "issue_comment:999",
        {"full_scan_complete": True},
    ) is False

    assert review["sidecars"]["deferred_gaps"] == {
        "issue_comment:210": {
            "reason": "artifact_missing",
            "full_scan_complete": True,
        }
    }


def test_bookkeeping_owner_lazily_materializes_observer_watermark_shape(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    floor = deferred_gap_bookkeeping.begin_observer_surface_scan(runtime, review, "reviews_dismissed")

    watermark = review["sidecars"]["observer_discovery_watermarks"]["reviews_dismissed"]
    assert watermark == {
        "last_scan_started_at": "2026-03-18T00:00:00+00:00",
        "last_scan_completed_at": None,
        "last_safe_event_time": None,
        "last_safe_event_id": None,
        "lookback_seconds": runtime.DEFERRED_DISCOVERY_OVERLAP_SECONDS,
        "bootstrap_window_seconds": runtime.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS,
        "bootstrap_completed_at": None,
    }
    assert floor.isoformat() == "2026-03-11T00:00:00+00:00"


def test_bookkeeping_owner_records_observer_watermark_event_and_empty_scan(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    deferred_gap_bookkeeping.record_observer_watermark_event(
        runtime,
        review,
        "reviews_dismissed",
        "2026-03-17T12:30:00+02:30",
        "12",
    )
    deferred_gap_bookkeeping.record_observer_watermark_empty_scan(runtime, review, "review_comments")

    dismissed = review["sidecars"]["observer_discovery_watermarks"]["reviews_dismissed"]
    assert dismissed["last_safe_event_time"] == "2026-03-17T10:00:00+00:00"
    assert dismissed["last_safe_event_id"] == "12"
    assert dismissed["last_scan_completed_at"] == "2026-03-18T00:00:00+00:00"
    comments = review["sidecars"]["observer_discovery_watermarks"]["review_comments"]
    assert comments["last_scan_started_at"] == "2026-03-18T00:00:00+00:00"
    assert comments["last_scan_completed_at"] == "2026-03-18T00:00:00+00:00"


def test_bookkeeping_owner_begins_observer_scan_and_returns_overlap_floor(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["observer_discovery_watermarks"]["reviews_dismissed"] = {
        "last_scan_started_at": None,
        "last_scan_completed_at": None,
        "last_safe_event_time": "2026-03-17T10:00:00Z",
        "last_safe_event_id": "12",
        "lookback_seconds": None,
        "bootstrap_window_seconds": None,
        "bootstrap_completed_at": None,
    }
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    floor = deferred_gap_bookkeeping.begin_observer_surface_scan(runtime, review, "reviews_dismissed")

    watermark = review["sidecars"]["observer_discovery_watermarks"]["reviews_dismissed"]
    assert watermark["last_scan_started_at"] == "2026-03-18T00:00:00+00:00"
    assert watermark["lookback_seconds"] == runtime.DEFERRED_DISCOVERY_OVERLAP_SECONDS
    assert watermark["bootstrap_window_seconds"] == runtime.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS
    assert floor.isoformat() == "2026-03-17T09:00:00+00:00"


def test_update_deferred_gap_preserves_first_noted_and_refreshes_last_checked(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {
        "first_noted_at": "2026-03-17T09:00:00+00:00",
        "last_checked_at": "2026-03-17T09:00:00+00:00",
    }
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    changed = deferred_gap_bookkeeping.record_deferred_gap_diagnostic(
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
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
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
    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-comment-router.yml"
    assert review["sidecars"]["deferred_gaps"]["issue_comment:210"]["source_artifact_name"] == "reviewer-bot-comment-context-700-attempt-1"


def test_update_deferred_gap_preserves_existing_workflow_artifact_provenance_when_payload_omits_it(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {
        "source_run_id": 700,
        "source_run_attempt": 1,
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
        "source_artifact_name": "reviewer-bot-comment-context-700-attempt-1",
    }
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    changed = deferred_gap_bookkeeping.record_deferred_gap_diagnostic(
        runtime,
        review,
        {
            "source_event_key": "issue_comment:210",
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "pr_number": 42,
            "source_created_at": "2026-03-17T10:00:00Z",
        },
        "reconcile_failed_closed",
        "Trusted sweeper diagnostics for issue_comment:210.",
    )

    assert changed is True
    gap = review["sidecars"]["deferred_gaps"]["issue_comment:210"]
    assert gap["source_run_id"] == 700
    assert gap["source_run_attempt"] == 1
    assert gap["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-comment-router.yml"
    assert gap["source_artifact_name"] == "reviewer-bot-comment-context-700-attempt-1"


def test_deferred_gap_diagnostic_retains_normalized_comment_source_evidence(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    changed = deferred_gap_bookkeeping.record_deferred_gap_diagnostic(
        runtime,
        review,
        {
            "source_event_key": "issue_comment:210",
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "pr_number": 42,
            "comment_created_at": "2026-03-17T10:00:00Z",
            "comment_id": 210,
            "comment_author": "alice",
            "comment_author_id": 7001,
            "comment_user_type": "User",
            "comment_sender_type": "User",
            "comment_installation_id": "12345",
            "comment_performed_via_github_app": False,
        },
        "reconcile_failed_closed",
        "comment replay failed closed",
    )

    assert changed is True
    gap = review["sidecars"]["deferred_gaps"]["issue_comment:210"]
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00+00:00"
    assert gap["source_actor_login"] == "alice"
    assert gap["source_actor_id"] == 7001
    assert gap["source_actor_user_type"] == "User"
    assert gap["source_actor_sender_type"] == "User"
    assert gap["source_actor_installation_id"] == "12345"
    assert gap["source_actor_performed_via_github_app"] is False
    assert gap["source_comment_id"] == 210

    deferred_gap_bookkeeping.record_deferred_gap_diagnostic(
        runtime,
        review,
        {
            "source_event_key": "issue_comment:210",
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "pr_number": 42,
        },
        "artifact_missing",
        "later diagnostic omitted actor fields",
    )

    gap = review["sidecars"]["deferred_gaps"]["issue_comment:210"]
    assert gap["source_actor_login"] == "alice"
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00+00:00"


def test_update_deferred_gap_preserves_source_dismissed_at_diagnostics(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    runtime.clock.now = lambda: runtime.datetime(2026, 3, 18, tzinfo=runtime.timezone.utc)

    changed = deferred_gap_bookkeeping.record_deferred_gap_diagnostic(
        runtime,
        review,
        {
            "source_event_key": "pull_request_review_dismissed:12",
            "source_event_name": "pull_request_review",
            "source_event_action": "dismissed",
            "pr_number": 42,
            "source_dismissed_at": "not-a-timestamp",
        },
        "reconcile_failed_closed",
        "dismissal timestamp invalid",
    )

    assert changed is True
    gap = review["sidecars"]["deferred_gaps"]["pull_request_review_dismissed:12"]
    assert gap["source_event_created_at"] == "not-a-timestamp"
    assert gap["source_dismissed_at"] == "not-a-timestamp"
