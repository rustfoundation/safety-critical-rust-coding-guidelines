from scripts import reviewer_bot
from tests.fixtures.github import RouteGitHubApi, github_result
from tests.fixtures.reviewer_bot import (
    accept_contributor_comment,
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


def test_project_status_labels_uses_live_current_reviewer_review_when_channel_state_missing(monkeypatch):
    state = make_state()
    make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(
                10,
                state="COMMENTED",
                submitted_at="2026-03-17T10:01:00Z",
                commit_id="head-1",
                author="alice",
            )
        ],
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_compute_reviewer_response_state_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(
                10,
                state="COMMENTED",
                submitted_at="2026-03-17T10:01:00Z",
                commit_id="head-1",
                author="alice",
            ),
            review_payload(
                99,
                state="COMMENTED",
                submitted_at="2026-03-17T11:00:00Z",
                commit_id="head-0",
                author="alice",
            ),
        ],
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")
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
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(
                10,
                state="COMMENTED",
                submitted_at="2026-03-17T10:01:00Z",
                commit_id="head-1",
                author="alice",
            ),
            review_payload(
                99,
                state="COMMENTED",
                submitted_at="2026-03-17T11:00:00Z",
                commit_id="head-0",
                author="alice",
            ),
        ],
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_repair_missing_reviewer_review_state_refreshes_to_preferred_current_head_review(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", pull_request_payload(42, head_sha="head-1"))
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    10,
                    state="COMMENTED",
                    submitted_at="2026-03-17T10:00:00Z",
                    commit_id="head-1",
                    author="alice",
                ),
                review_payload(
                    99,
                    state="COMMENTED",
                    submitted_at="2026-03-17T11:00:00Z",
                    commit_id="head-0",
                    author="alice",
                ),
            ],
        )
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    assert reviewer_bot.reviews_module.repair_missing_reviewer_review_state(reviewer_bot, 42, review) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"
    assert "pull_request_review:99" in review["reviewer_review"]["seen_keys"]


def test_refresh_reviewer_review_from_live_preferred_review_returns_true_for_activity_only_change(monkeypatch):
    review = make_tracked_review_state(
        make_state(),
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
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
    routes = (
        RouteGitHubApi()
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    10,
                    state="COMMENTED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="alice",
                )
            ],
        )
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

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


def test_project_status_labels_uses_commit_id_and_comment_freshness(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", pull_request_payload(42, head_sha="head-2"))
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-2"))
        .add_request("GET", "pulls/42/reviews?per_page=100&page=1", status_code=200, payload=[])
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


def test_compute_reviewer_response_state_keeps_contributor_handoff_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    accept_contributor_revision(
        review,
        semantic_key="pull_request_sync:42:head-1",
        timestamp="2026-03-17T12:00:00Z",
        actor="alice",
        head_sha="head-1",
    )
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", pull_request_payload(42, head_sha="head-1"))
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    99,
                    state="COMMENTED",
                    submitted_at="2026-03-17T11:00:00Z",
                    commit_id="head-0",
                    author="alice",
                )
            ],
        )
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "contributor_revision_newer"


def test_project_status_labels_pr256_shape_remains_awaiting_contributor_response(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="vccjgust",
        active_cycle_started_at="2026-02-18T09:00:00Z",
    )
    accept_contributor_comment(
        review,
        semantic_key="issue_comment:20",
        timestamp="2026-02-18T09:30:00Z",
        actor="dana",
    )
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", pull_request_payload(42, head_sha="head-current"))
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-current"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    30,
                    state="COMMENTED",
                    submitted_at="2026-02-18T10:00:00Z",
                    commit_id="head-older",
                    author="vccjgust",
                ),
                review_payload(
                    31,
                    state="COMMENTED",
                    submitted_at="2026-02-18T11:00:00Z",
                    commit_id="head-current",
                    author="vccjgust",
                ),
            ],
        )
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_project_status_labels_prefers_newer_contributor_comment_over_live_review_fallback(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_contributor_comment(
        review,
        semantic_key="issue_comment:20",
        timestamp="2026-03-17T10:05:00Z",
        actor="bob",
    )
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", pull_request_payload(42, head_sha="head-1"))
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    10,
                    state="COMMENTED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="alice",
                )
            ],
        )
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    monkeypatch.setattr(reviewer_bot, "github_api", routes.github_api)
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "contributor_comment_newer"


def test_project_status_labels_emits_awaiting_write_approval_only_after_completion(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    routes = (
        RouteGitHubApi()
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    10,
                    state="APPROVED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="bob",
                )
            ],
        )
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "denied")

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}
    assert metadata["state"] == "awaiting_write_approval"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels_again == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}


def test_compute_reviewer_response_state_reports_pull_request_unavailable(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_unavailable"


def test_compute_reviewer_response_state_fails_closed_without_stored_activity_when_pr_head_invalid(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        status_code=200,
        payload={"state": "open", "head": {}},
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_head_unavailable"


def test_compute_reviewer_response_state_reports_permission_unavailable(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True),
    )
    routes = (
        RouteGitHubApi()
        .add_request("GET", "pulls/42", status_code=200, payload=pull_request_payload(42, head_sha="head-1"))
        .add_request(
            "GET",
            "pulls/42/reviews?per_page=100&page=1",
            status_code=200,
            payload=[
                review_payload(
                    10,
                    state="APPROVED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="alice",
                )
            ],
        )
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", routes.github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "permission_unavailable"
