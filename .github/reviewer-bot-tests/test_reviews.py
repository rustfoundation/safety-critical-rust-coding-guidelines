import json

import pytest
from factories import make_state

from scripts import reviewer_bot


def test_project_status_labels_uses_commit_id_and_comment_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-2"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"

def test_project_status_labels_uses_live_current_reviewer_review_when_channel_state_missing(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"

def test_project_status_labels_uses_live_review_fallback_for_stale_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-2"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"

def test_project_status_labels_prefers_current_head_review_over_newer_stale_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 11,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:01:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"

def test_compute_reviewer_response_state_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_contributor_response"
    assert response_state["reason"] == "completion_missing"
    assert response_state["reviewer_review"]["semantic_key"] == "pull_request_review:10"
    assert response_state["reviewer_review"]["reviewed_head_sha"] == "head-1"

def test_project_status_labels_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"

def test_compute_reviewer_response_state_keeps_contributor_handoff_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_revision",
        semantic_key="pull_request_sync:42:head-1",
        timestamp="2026-03-17T12:00:00Z",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "contributor_revision_newer"

def test_project_status_labels_pr256_shape_remains_awaiting_contributor_response(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "vccjgust"
    review["active_cycle_started_at"] = "2026-02-18T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_comment",
        semantic_key="issue_comment:20",
        timestamp="2026-02-18T09:30:00Z",
        actor="dana",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-current"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 30,
                "state": "COMMENTED",
                "submitted_at": "2026-02-18T10:00:00Z",
                "commit_id": "head-older",
                "user": {"login": "vccjgust"},
            },
            {
                "id": 31,
                "state": "COMMENTED",
                "submitted_at": "2026-02-18T11:00:00Z",
                "commit_id": "head-current",
                "user": {"login": "vccjgust"},
            },
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"

def test_project_status_labels_prefers_newer_contributor_comment_over_live_review_fallback(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_comment",
        semantic_key="issue_comment:20",
        timestamp="2026-03-17T10:05:00Z",
        actor="bob",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "contributor_comment_newer"

def test_record_reviewer_activity_does_not_regress_timestamp_on_legacy_backfill():
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["last_reviewer_activity"] = "2026-03-20T10:00:00Z"
    review["transition_warning_sent"] = "2026-03-21T10:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-22T10:00:00Z"
    reviewer_bot.reviews_module.record_reviewer_activity(review, "2026-03-18T10:00:00Z")
    assert review["last_reviewer_activity"] == "2026-03-20T10:00:00Z"
    assert review["transition_warning_sent"] == "2026-03-21T10:00:00Z"
    assert review["transition_notice_sent_at"] == "2026-03-22T10:00:00Z"

def test_project_status_labels_emits_awaiting_write_approval_only_after_completion(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"state": "open", "head": {"sha": "head-1"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload=[
                    {
                        "id": 10,
                        "state": "APPROVED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "bob"},
                    }
                ],
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "denied")
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}
    assert metadata["state"] == "awaiting_write_approval"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels_again == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}

def test_compute_reviewer_response_state_reports_pull_request_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_unavailable"

def test_compute_reviewer_response_state_fails_closed_without_stored_activity_when_pr_head_invalid(
    monkeypatch,
):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {}},
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_head_unavailable"

def test_compute_reviewer_response_state_reports_permission_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"state": "open", "head": {"sha": "head-1"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload=[
                    {
                        "id": 10,
                        "state": "APPROVED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "alice"},
                    }
                ],
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "permission_unavailable"

def test_list_open_items_with_status_labels_fails_closed_on_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="server_error"):
        reviewer_bot.list_open_items_with_status_labels()

def test_repair_missing_reviewer_review_state_refreshes_to_preferred_current_head_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:00:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    assert reviewer_bot.reviews_module.repair_missing_reviewer_review_state(reviewer_bot, 42, review) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"
    assert "pull_request_review:99" in review["reviewer_review"]["seen_keys"]

def test_refresh_reviewer_review_from_live_preferred_review_returns_true_for_activity_only_change(
    monkeypatch,
):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
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
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "COMMENTED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    changed, preferred_review = reviewer_bot.reviews_module.refresh_reviewer_review_from_live_preferred_review(
        reviewer_bot,
        42,
        review,
    )

    assert changed is True
    assert preferred_review is not None
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None

def test_compute_reviewer_response_state_is_pure_for_pr_projection(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    before = json.loads(json.dumps(review))
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}} if endpoint == "pulls/42" else [],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert review == before

def test_compute_pr_approval_state_result_is_pure(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    before = json.loads(json.dumps(review))
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "APPROVED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    result = reviewer_bot.reviews_module.compute_pr_approval_state_result(reviewer_bot, 42, review)

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert review == before

def test_apply_pr_approval_state_mutates_expected_fields():
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None

    reviewer_bot.reviews_module.apply_pr_approval_state(
        review,
        completion={"completed": True, "current_head_sha": "head-1", "qualifying_review_ids": [10]},
        write_approval={"has_write_approval": True, "write_approvers": ["alice"], "current_head_sha": "head-1"},
        current_head_sha="head-1",
    )

    assert review["active_head_sha"] == "head-1"
    assert review["current_cycle_completion"]["completed"] is True
    assert review["current_cycle_write_approval"]["has_write_approval"] is True
    assert review["review_completion_source"] == "live_review_rebuild"

def test_get_pull_request_reviews_result_paginates(monkeypatch):
    responses = {
        "pulls/42/reviews?per_page=100&page=1": reviewer_bot.GitHubApiResult(200, [{"id": i} for i in range(100)], {}, "ok", True, None, 0, None),
        "pulls/42/reviews?per_page=100&page=2": reviewer_bot.GitHubApiResult(200, [{"id": 100}], {}, "ok", True, None, 0, None),
    }
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: responses[endpoint],
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result["ok"] is True
    assert len(result["reviews"]) == 101

def test_get_pull_request_reviews_result_uses_fallback_loader_after_system_exit(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [{"id": 10}])

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}

def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, {"not": "a list"}, {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}

def test_pull_request_read_result_reports_not_found(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_not_found", "failure_kind": "not_found"}

def test_pull_request_read_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, ["not", "a", "dict"], {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}
