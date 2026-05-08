from types import SimpleNamespace

from scripts.reviewer_bot_core import approval_policy
from scripts.reviewer_bot_lib import review_state, reviews
from scripts.reviewer_bot_lib.config import (
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
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
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: github_result(200, [])
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    if routes is not None:
        runtime.github.stub(routes)
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
    assert metadata["reason"] == "assigned_reviewer_review_submitted"


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
    assert response_state["reason"] == "assigned_reviewer_review_submitted"
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


def test_accept_reviewer_review_from_live_review_accepts_matching_current_reviewer_review_payload(monkeypatch):
    review = make_tracked_review_state(make_state(), 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    live_review = review_payload(
        10,
        state="COMMENTED",
        submitted_at="2026-03-17T10:01:00Z",
        commit_id="head-1",
        author="alice",
    )

    changed = review_state.accept_reviewer_review_from_live_review(review, live_review)

    assert changed is True
    assert review["reviewer_review"]["accepted"]["semantic_key"] == "pull_request_review:10"
    assert review["reviewer_review"]["accepted"]["reviewed_head_sha"] == "head-1"


def test_refresh_reviewer_review_from_live_preferred_review_returns_false_for_reviewer_mismatch(monkeypatch):
    review = make_tracked_review_state(make_state(), 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="bob")],
    )
    runtime = _runtime(monkeypatch, routes)

    changed, preferred_review = review_state.refresh_reviewer_review_from_live_preferred_review(runtime, 42, review)

    assert changed is False
    assert preferred_review is None
    assert review["reviewer_review"]["accepted"] is None


def test_refresh_reviewer_review_from_live_preferred_review_returns_false_when_no_preferred_review_found(monkeypatch):
    review = make_tracked_review_state(make_state(), 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)

    changed, preferred_review = review_state.refresh_reviewer_review_from_live_preferred_review(runtime, 42, review)

    assert changed is False
    assert preferred_review is None


def test_repair_missing_reviewer_review_state_backfills_live_review_payload_when_record_is_partial(monkeypatch):
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
    review["last_reviewer_activity"] = "2026-03-17T10:01:00Z"
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)

    before = {
        "reviewer_review": review["reviewer_review"].copy(),
        "last_reviewer_activity": review["last_reviewer_activity"],
        "transition_warning_sent": review.get("transition_warning_sent"),
        "transition_notice_sent_at": review.get("transition_notice_sent_at"),
    }

    assert review_state.repair_missing_reviewer_review_state(runtime, 42, review) is True
    assert review["reviewer_review"]["accepted"]["semantic_key"] == before["reviewer_review"]["accepted"]["semantic_key"]
    assert review["reviewer_review"]["accepted"]["payload"]["state"] == "COMMENTED"
    assert review["last_reviewer_activity"] == before["last_reviewer_activity"]
    assert review.get("transition_warning_sent") == before["transition_warning_sent"]
    assert review.get("transition_notice_sent_at") == before["transition_notice_sent_at"]


def test_project_status_labels_ignores_pr_reviewer_comment_when_review_head_stale(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_comment(review, semantic_key="issue_comment:1", timestamp="2026-03-17T10:00:00Z", actor="alice")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-2")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)

    desired_labels, metadata = reviews.project_status_labels_for_item(runtime, 42, state)

    assert desired_labels == {STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


def test_compute_reviewer_response_state_ignores_persisted_pr264_plain_comment_poison(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-26T04:58:03.401345+00:00",
        active_cycle_started_at="2026-02-26T04:58:03.401345+00:00",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:77",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
        source_precedence=1,
    )
    accept_contributor_revision(
        review,
        semantic_key="pull_request_sync:264:7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
        timestamp="2026-03-18T12:09:36.450502+00:00",
        actor="manhatsu",
        head_sha="7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:4240237244",
        timestamp="2026-04-13T23:23:25Z",
        actor="iglesias",
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(
        264,
        pull_request_payload(264, head_sha="7d8864fa0c00b5bf9da20dd66047f039a049fd8b", author="manhatsu"),
    ).add_pull_request_reviews(
        264,
        [
            review_payload(77, state="COMMENTED", submitted_at="2026-03-18T01:09:05Z", commit_id="head-old", author="iglesias"),
            review_payload(
                501,
                state="APPROVED",
                submitted_at="2026-03-18T12:10:42Z",
                commit_id="7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
                author="plaindocs",
            ),
        ],
    )
    runtime = _runtime(monkeypatch, routes)

    response_state = reviews.compute_reviewer_response_state(runtime, 264, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "contributor_revision_newer"
    assert response_state["reviewer_comment"] is None
    assert response_state["anchor_timestamp"] == "2026-03-18T12:09:36.450502+00:00"
    assert response_state["current_scope_basis"] == "contributor_revision"


def test_compute_reviewer_response_state_reports_review_head_stale_when_current_head_has_no_matching_review(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-2")).add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "review_head_stale"


def test_compute_reviewer_response_state_reports_awaiting_write_approval_after_completion(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_user_permission_status = lambda username, required_permission="triage": "denied"

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "awaiting_write_approval"
    assert response_state["reason"] == "write_approval_missing"


def test_compute_reviewer_response_state_uses_assignment_guidance_for_claim_alternate_approval_scope(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="iglesias",
        assigned_at="2026-02-26T04:58:03.401345+00:00",
    )
    review["assignment_method"] = "claim"
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
        source_precedence=1,
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-live")).add_pull_request_reviews(
        42,
        [review_payload(10, state="APPROVED", submitted_at="2026-03-18T12:10:42Z", commit_id="head-live", author="plaindocs")],
    ).add_request(
        "GET",
        "issues/42/comments?per_page=100&page=1",
        status_code=200,
        payload=[
            {
                "user": {"login": "github-actions"},
                "created_at": "2026-02-10T17:20:07Z",
                "body": "👋 Hey @iglesias! You've been assigned to review this coding guideline PR.\n\n## Your Role as Reviewer",
            }
        ],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {
        **issue_snapshot(issue_number, state="open", is_pull_request=True),
        "created_at": "2025-12-08T04:16:34Z",
    }

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "review_head_stale"


def test_compute_reviewer_response_state_blocks_public_current_head_approval_contradiction_before_refresh(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T09:30:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "done"
    assert response_state["reason"] == "write_approval_present"


def test_rebuild_pr_approval_state_does_not_persist_completion_from_alternate_approval(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [review_payload(11, state="APPROVED", submitted_at="2026-03-17T10:05:00Z", commit_id="head-1", author="bob")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    completion, write_approval = reviews.rebuild_pr_approval_state(runtime, 42, review)

    assert completion["completed"] is False
    assert completion["current_head_sha"] == "head-1"
    assert completion["qualifying_review_ids"] == []
    assert write_approval["has_write_approval"] is False
    assert write_approval["write_approvers"] == []
    assert write_approval["current_head_sha"] == "head-1"
    assert review["review_completed_at"] is None
    assert review["review_completion_source"] is None


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
        [
            review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice"),
            review_payload(11, state="APPROVED", submitted_at="2026-03-17T10:05:00Z", commit_id="head-1", author="bob"),
        ],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_user_permission_status = lambda username, required_permission="triage": "denied"

    desired_labels, metadata = reviews.project_status_labels_for_item(runtime, 42, state)

    assert desired_labels == {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["state"] == "awaiting_contributor_response"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviews.project_status_labels_for_item(runtime, 42, state)
    assert desired_labels_again == {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}


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
    runtime.github.get_user_permission_status = lambda username, required_permission="triage": "unavailable"

    response_state = reviews.compute_reviewer_response_state(runtime, 42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "live_review_state_unknown"
    assert response_state["write_approval_authority"] == {
        "issue_number": 42,
        "head_sha": "head-1",
        "assigned_reviewer": "alice",
        "assigned_review_id": 10,
        "assigned_review_state": "APPROVED",
        "assigned_round_complete": True,
        "write_approval_state": "blocked_unavailable_authority",
        "write_approval_source": "github_permission_read_unavailable",
        "approving_reviewer": "alice",
        "approving_review_id": 10,
        "permission_source": "github_permission_read",
        "dismissal_supersession_status": "blocked_untrusted",
        "response_state": "projection_failed",
        "diagnostic_reason": "permission_unavailable",
        "can_project_final_state": False,
    }


def test_trigger_mandatory_approver_escalation_sets_required_label_and_ping(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    comments = []
    labels = []

    def github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        assert method == "POST"
        assert endpoint == "issues/42/labels"
        labels.append((42, data["labels"][0]))
        return SimpleNamespace(status_code=200, text="ok")

    runtime = SimpleNamespace(
        github=SimpleNamespace(
            ensure_label_exists=lambda label: True,
            post_comment=lambda issue_number, body: comments.append((issue_number, body)) or True,
        ),
        github_api_request=github_api_request,
        logger=SimpleNamespace(event=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(reviews, "_now_iso", lambda: "2026-03-21T10:00:00+00:00")

    changed = reviews.trigger_mandatory_approver_escalation(runtime, state, 42)

    assert changed is True
    assert review["mandatory_approver_required"] is True
    assert review["mandatory_approver_label_applied_at"] == "2026-03-21T10:00:00+00:00"
    assert review["mandatory_approver_pinged_at"] == "2026-03-21T10:00:00+00:00"
    assert labels == [(42, reviews.MANDATORY_TRIAGE_APPROVER_LABEL)]
    assert comments == [(42, reviews.MANDATORY_TRIAGE_ESCALATION_TEMPLATE)]


def test_rebuild_pr_approval_state_applies_core_result_as_retained_execution_support(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    monkeypatch.setattr(
        approval_policy,
        "compute_pr_approval_state_result",
        lambda bot, issue_number, review_data, **kwargs: {
            "ok": True,
            "completion": {"completed": True},
            "write_approval": {"has_write_approval": True},
            "current_head_sha": "head-1",
        },
    )

    completion, write_approval = reviews.rebuild_pr_approval_state(SimpleNamespace(), 42, review)

    assert completion == {"completed": True}
    assert write_approval == {"has_write_approval": True}
    assert review["active_head_sha"] == "head-1"
    assert review["review_completion_source"] == "live_review_rebuild"


def test_satisfy_mandatory_approver_requirement_clears_required_and_records_satisfaction(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    review["mandatory_approver_required"] = True
    removed = []
    comments = []

    def github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        assert method == "DELETE"
        assert endpoint.startswith("issues/42/labels/")
        removed.append((42, reviews.MANDATORY_TRIAGE_APPROVER_LABEL))
        return SimpleNamespace(status_code=204, text="ok")

    runtime = SimpleNamespace(
        github_api_request=github_api_request,
        github=SimpleNamespace(post_comment=lambda issue_number, body: comments.append((issue_number, body)) or True),
        logger=SimpleNamespace(event=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(reviews, "_now_iso", lambda: "2026-03-21T11:00:00+00:00")

    changed = reviews.satisfy_mandatory_approver_requirement(runtime, state, 42, "carol")

    assert changed is True
    assert review["mandatory_approver_required"] is False
    assert review["mandatory_approver_satisfied_by"] == "carol"
    assert review["mandatory_approver_satisfied_at"] == "2026-03-21T11:00:00+00:00"
    assert removed == [(42, reviews.MANDATORY_TRIAGE_APPROVER_LABEL)]
    assert comments == [(42, reviews.MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver="carol"))]
