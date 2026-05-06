from datetime import timedelta
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_core import approval_policy
from scripts.reviewer_bot_lib import maintenance, overdue, review_state
from scripts.reviewer_bot_lib.repair_records import load_repair_marker
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import (
    accept_contributor_comment,
    accept_contributor_revision,
    accept_reviewer_comment,
    accept_reviewer_review,
    iso_z,
    issue_snapshot,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi


def _runtime(monkeypatch, routes=None):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    if routes is not None:
        runtime.github.stub(routes)
    return runtime


def _approval_incomplete_result(*_args, **_kwargs):
    return {
        "ok": True,
        "completion": {"completed": False},
        "write_approval": {"has_write_approval": False},
        "current_head_sha": "head-1",
    }


def test_reminder_cadence_normalizes_timezone_less_anchor_to_utc():
    decision = overdue.derive_reminder_cadence_decision(
        SimpleNamespace(
            scope=SimpleNamespace(issue_number=42, reviewer="alice"),
            response_state="awaiting_reviewer_response",
            anchor_timestamp="2026-03-01T00:00:00",
        ),
        receipt=None,
        reminder_scan=None,
        now="2026-03-08T00:00:00+00:00",
        review_deadline_days=7,
        transition_period_days=14,
    )

    assert decision.cadence_state == "warning_due"
    assert decision.may_post_warning is True


def test_reminder_cadence_normalizes_offset_anchor_to_canonical_utc():
    decision = overdue.derive_reminder_cadence_decision(
        SimpleNamespace(
            scope=SimpleNamespace(issue_number=42, reviewer="alice"),
            response_state="awaiting_reviewer_response",
            anchor_timestamp="2026-03-01T02:30:00+02:30",
        ),
        receipt=None,
        reminder_scan=None,
        now="2026-03-08T00:00:00+00:00",
        review_deadline_days=7,
        transition_period_days=14,
    )

    assert decision.cadence_state == "warning_due"
    assert decision.may_post_warning is True


def test_check_overdue_reviews_skips_pr_with_current_head_reviewer_review(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-01T00:00:00Z", active_cycle_started_at="2026-03-01T00:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-02T00:00:00Z", actor="alice", reviewed_head_sha="head-1")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1"))
    runtime = _runtime(monkeypatch, routes)
    monkeypatch.setattr(approval_policy, "compute_pr_approval_state_result", _approval_incomplete_result)

    assert maintenance.check_overdue_reviews(runtime, state) == []


def test_check_overdue_reviews_consumes_only_stable_reviewer_response_fields(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    now = runtime.datetime.now(runtime.timezone.utc)
    anchor_timestamp = (now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 1)).replace(tzinfo=None).isoformat()
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice", assigned_at=anchor_timestamp, active_cycle_started_at=anchor_timestamp)
    runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: runtime.GitHubApiResult(
        200,
        issue_snapshot(issue_number, state="open", is_pull_request=True),
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": anchor_timestamp,
        "ignored": {"reviewer_review": "not consumed"},
    }
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    overdue = maintenance.check_overdue_reviews(runtime, state)

    assert overdue == [
        {
            "issue_number": 42,
            "reviewer": "alice",
            "days_overdue": 1,
            "days_since_warning": 0,
            "needs_warning": True,
            "needs_transition": False,
            "anchor_reason": None,
            "anchor_timestamp": anchor_timestamp,
            "current_scope_key": None,
            "current_scope_basis": None,
        }
    ]


def test_check_overdue_reviews_skips_item_when_snapshot_unavailable(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: runtime.GitHubApiResult(
        502,
        None,
        {},
        "bad gateway",
        False,
        "server_error",
        1,
        None,
    )

    assert maintenance.check_overdue_reviews(runtime, state) == []


def test_check_overdue_reviews_suppresses_stale_reviewer_authority_and_records_diagnostic(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    now = runtime.datetime.now(runtime.timezone.utc)
    anchor_timestamp = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 1))
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at=anchor_timestamp,
        active_cycle_started_at=anchor_timestamp,
    )
    runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: runtime.GitHubApiResult(
        200,
        issue_snapshot(issue_number, state="open", is_pull_request=False),
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["bob"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": anchor_timestamp,
    }

    assert maintenance.check_overdue_reviews(runtime, state) == []
    marker = load_repair_marker(review, "assignment_confirm_read")
    assert marker is not None
    assert marker["reason"] == "tracked_reviewer_missing_from_live_control_plane"


def test_handle_overdue_review_warning_only_records_successful_comment(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: runtime.GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.github.post_comment_result = lambda issue_number, body: runtime.GitHubApiResult(
        502,
        None,
        {},
        "bad gateway",
        False,
        "server_error",
        1,
        None,
    )

    assert maintenance.handle_overdue_review_warning(runtime, state, 42, "alice") is True
    assert review["transition_warning_sent"] is None
    assert load_repair_marker(review, "warning_post")["failure_kind"] == "server_error"


def test_handle_overdue_review_warning_uses_contributor_handoff_text(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    runtime = FakeReviewerBotRuntime(monkeypatch)
    posted = []
    runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: runtime.GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.github.post_comment_result = (
        lambda issue_number, body: posted.append(body)
        or runtime.GitHubApiResult(201, {}, {}, "created", True, None, 0, None)
    )

    assert maintenance.handle_overdue_review_warning(
        runtime,
        state,
        42,
        "alice",
        anchor_reason="contributor_comment_newer",
    ) is True
    assert "latest contributor follow-up returned this review to you" in posted[0]
    assert "since you were assigned" not in posted[0]
    assert posted[0].splitlines()[0] == "<!-- reviewer-bot:transition-warning:v1 issue=42 reviewer=alice anchor= -->"


def test_handle_overdue_review_warning_backfills_existing_marker_without_repost(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: runtime.GitHubApiResult(
        200,
        [
            {
                "id": 99,
                "created_at": "2026-03-25T15:22:42Z",
                "body": "<!-- reviewer-bot:transition-warning:v1 issue=42 reviewer=alice anchor= -->\n\n⚠️ **Review Reminder**\n\nExisting warning",
                "user": {"login": "guidelines-bot"},
            }
        ],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.github.post_comment_result = lambda issue_number, body: pytest.fail("warning backfill must not repost")

    assert maintenance.handle_overdue_review_warning(runtime, state, 42, "alice") is True
    assert review["transition_warning_sent"] == "2026-03-25T15:22:42Z"


def test_backfill_transition_notice_if_present_records_dedupe_failure_without_backfill(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: runtime.GitHubApiResult(
        502,
        None,
        {},
        "bad gateway",
        False,
        "server_error",
        1,
        None,
    )

    assert maintenance.backfill_transition_notice_if_present(runtime, state, 42) is True
    assert review.get("transition_notice_sent_at") is None
    assert load_repair_marker(review, "transition_dedupe_read")["failure_kind"] == "server_error"


def test_check_overdue_reviews_non_pr_contributor_followup_reanchors_to_contributor_timestamp(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    now = runtime.datetime.now(runtime.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 20))
    reviewer_comment_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 19))
    contributor_comment_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 1))
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at=assigned_at,
        active_cycle_started_at=assigned_at,
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:10",
        timestamp=reviewer_comment_at,
        actor="alice",
    )
    accept_contributor_comment(
        review,
        semantic_key="issue_comment:11",
        timestamp=contributor_comment_at,
        actor="dana",
    )
    runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: runtime.GitHubApiResult(
        200,
        issue_snapshot(issue_number, state="open", is_pull_request=False),
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    overdue = maintenance.check_overdue_reviews(runtime, state)

    assert overdue == [
        {
            "issue_number": 42,
            "reviewer": "alice",
            "days_overdue": 1,
            "days_since_warning": 0,
            "needs_warning": True,
            "needs_transition": False,
            "anchor_reason": "contributor_comment_newer",
            "anchor_timestamp": contributor_comment_at,
            "current_scope_key": f"reviewer=alice|head=none|cycle={assigned_at}|anchor={contributor_comment_at}",
            "current_scope_basis": "contributor_comment",
        }
    ]


def test_check_overdue_reviews_uses_contributor_comment_timestamp_when_turn_returns_to_reviewer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    now = runtime.datetime.now(runtime.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 19))
    contributor_comment_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS, minutes=1))
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at=assigned_at, active_cycle_started_at=assigned_at)
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp=reviewer_review_at, actor="alice", reviewed_head_sha="head-1")
    accept_contributor_comment(review, semantic_key="issue_comment:20", timestamp=contributor_comment_at, actor="bob")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    monkeypatch.setattr(approval_policy, "compute_pr_approval_state_result", _approval_incomplete_result)

    overdue = maintenance.check_overdue_reviews(runtime, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_uses_contributor_revision_timestamp_when_head_changes_after_review(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    now = runtime.datetime.now(runtime.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS + 19))
    contributor_revision_at = iso_z(now - timedelta(days=runtime.REVIEW_DEADLINE_DAYS, minutes=1))
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at=assigned_at, active_cycle_started_at=assigned_at)
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp=reviewer_review_at, actor="alice", reviewed_head_sha="head-1")
    accept_contributor_revision(review, semantic_key="pull_request_sync:42:head-2", timestamp=contributor_revision_at, actor="alice", head_sha="head-2")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-2")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    overdue = maintenance.check_overdue_reviews(runtime, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_ignores_same_head_contributor_revision_after_valid_reviewer_review(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-01T00:00:00Z", active_cycle_started_at="2026-03-01T00:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-02T00:00:00Z", actor="alice", reviewed_head_sha="head-1")
    accept_contributor_revision(review, semantic_key="pull_request_head_observed:42:head-1", timestamp="2026-03-12T00:00:00Z", actor="alice", head_sha="head-1")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)
    monkeypatch.setattr(approval_policy, "compute_pr_approval_state_result", _approval_incomplete_result)

    assert maintenance.check_overdue_reviews(runtime, state) == []


def test_check_overdue_reviews_uses_live_current_head_review_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-01T00:00:00Z", active_cycle_started_at="2026-03-01T00:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-02T00:00:00Z", actor="alice", reviewed_head_sha="head-0")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(10, state="COMMENTED", submitted_at="2026-03-20T00:00:00Z", commit_id="head-1", author="alice"),
            review_payload(99, state="COMMENTED", submitted_at="2026-03-21T00:00:00Z", commit_id="head-0", author="alice"),
        ],
    )
    runtime = _runtime(monkeypatch, routes)
    monkeypatch.setattr(approval_policy, "compute_pr_approval_state_result", _approval_incomplete_result)

    assert maintenance.check_overdue_reviews(runtime, state) == []


def test_refresh_reviewer_review_from_live_preferred_review_does_not_clear_transition_warning_when_activity_not_advanced(monkeypatch):
    review = make_tracked_review_state(make_state(), 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    review["reviewer_review"] = {
        "accepted": {
            "semantic_key": "pull_request_review:10",
            "timestamp": "2026-03-17T10:01:00Z",
            "actor": "alice",
            "reviewed_head_sha": "head-1",
            "source_precedence": 1,
            "payload": {},
        },
        "seen_keys": ["pull_request_review:10"],
    }
    review["last_reviewer_activity"] = "2026-03-17T10:01:00Z"
    review["transition_warning_sent"] = "2026-04-01T12:12:04Z"
    review["transition_notice_sent_at"] = "2026-04-15T12:12:04Z"
    routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [{"id": 10, "state": "COMMENTED", "submitted_at": "2026-03-17T10:01:00Z", "commit_id": "head-1", "user": {"login": "alice"}}],
    )
    runtime = _runtime(monkeypatch, routes)

    changed, preferred_review = review_state.refresh_reviewer_review_from_live_preferred_review(runtime, 42, review)

    assert changed is True
    assert preferred_review is not None
    assert review["reviewer_review"]["accepted"]["payload"]["state"] == "COMMENTED"
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"
    assert review["transition_warning_sent"] == "2026-04-01T12:12:04Z"
    assert review["transition_notice_sent_at"] == "2026-04-15T12:12:04Z"
