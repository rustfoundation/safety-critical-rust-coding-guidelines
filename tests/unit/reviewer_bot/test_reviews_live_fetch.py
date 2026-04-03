from scripts.reviewer_bot_lib import review_state, reviews
from scripts.reviewer_bot_lib.config import (
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import (
    accept_contributor_revision,
    accept_reviewer_comment,
    accept_reviewer_review,
    accepted_record,
    issue_snapshot,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def _runtime(monkeypatch, routes=None):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.get_user_permission_status = lambda username, required_permission="push": "granted"
    if routes is not None:
        runtime.stub_github(routes)
    return runtime


def test_project_status_labels_uses_live_current_reviewer_review_when_channel_state_missing(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)

    desired_labels, metadata = reviews.project_status_labels_for_item(runtime, 42, state)

    assert desired_labels == {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_compute_reviewer_response_state_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-17T11:00:00Z", actor="alice", reviewed_head_sha="head-0", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice"),
            review_payload(99, state="COMMENTED", submitted_at="2026-03-17T11:00:00Z", commit_id="head-0", author="alice"),
        ],
    )
    runtime = _runtime(monkeypatch, routes)
    monkeypatch.setattr(reviews, "rebuild_pr_approval_state", lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}))

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "awaiting_contributor_response"
    assert response_state["reason"] == "completion_missing"
    assert response_state["reviewer_review"]["semantic_key"] == "pull_request_review:10"
    assert response_state["reviewer_review"]["reviewed_head_sha"] == "head-1"


def test_repair_missing_reviewer_review_state_refreshes_to_preferred_current_head_review(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-17T11:00:00Z", actor="alice", reviewed_head_sha="head-0", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:00:00Z", commit_id="head-1", author="alice"),
            review_payload(99, state="COMMENTED", submitted_at="2026-03-17T11:00:00Z", commit_id="head-0", author="alice"),
        ],
    )
    runtime = _runtime(monkeypatch, routes)

    assert review_state.repair_missing_reviewer_review_state(runtime, 42, review) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"


def test_refresh_reviewer_review_from_live_preferred_review_returns_true_for_activity_only_change(monkeypatch):
    review = make_tracked_review_state(make_state(), 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    review["reviewer_review"] = {
        "accepted": {
            **accepted_record(
                semantic_key="pull_request_review:10",
                timestamp="2026-03-17T10:01:00Z",
                actor="alice",
                reviewed_head_sha="head-1",
            ),
            "source_precedence": 1,
            "payload": {},
        },
        "seen_keys": ["pull_request_review:10"],
    }
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)

    changed, preferred_review = review_state.refresh_reviewer_review_from_live_preferred_review(runtime, 42, review)

    assert changed is True
    assert preferred_review is not None
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_project_status_labels_uses_commit_id_and_comment_freshness(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_comment(review, semantic_key="issue_comment:1", timestamp="2026-03-17T10:00:00Z", actor="alice")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-2")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)

    desired_labels, metadata = reviews.project_status_labels_for_item(runtime, 42, state)

    assert desired_labels == {STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


def test_compute_reviewer_response_state_keeps_contributor_handoff_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-17T11:00:00Z", actor="alice", reviewed_head_sha="head-0", source_precedence=1)
    accept_contributor_revision(review, semantic_key="pull_request_sync:42:head-1", timestamp="2026-03-17T12:00:00Z", actor="alice", head_sha="head-1")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(99, state="COMMENTED", submitted_at="2026-03-17T11:00:00Z", commit_id="head-0", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "contributor_revision_newer"


def test_project_status_labels_emits_awaiting_write_approval_only_after_completion(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_comment(review, semantic_key="issue_comment:1", timestamp="2026-03-17T10:00:00Z", actor="alice")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="bob")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.get_user_permission_status = lambda username, required_permission="triage": "denied"

    desired_labels, metadata = reviews.project_status_labels_for_item(runtime, 42, state)

    assert desired_labels == {STATUS_AWAITING_WRITE_APPROVAL_LABEL}
    assert metadata["state"] == "awaiting_write_approval"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviews.project_status_labels_for_item(runtime, 42, state)
    assert desired_labels_again == {STATUS_AWAITING_WRITE_APPROVAL_LABEL}


def test_compute_reviewer_response_state_reports_pull_request_unavailable(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    routes = RouteGitHubApi().add_request("GET", "pulls/42", result=github_result(502, {"message": "bad gateway"}, retry_attempts=1))
    runtime = _runtime(monkeypatch, routes)

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_unavailable"


def test_compute_reviewer_response_state_fails_closed_without_stored_activity_when_pr_head_invalid(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {}})
    runtime = _runtime(monkeypatch, routes)

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_head_unavailable"


def test_compute_reviewer_response_state_reports_permission_unavailable(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "live_review_state_unknown"
