from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


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


def test_refresh_reviewer_review_from_live_preferred_review_returns_true_for_activity_only_change(monkeypatch):
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
