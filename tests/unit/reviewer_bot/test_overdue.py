from datetime import timedelta

from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import iso_z, make_state


def test_check_overdue_reviews_skips_pr_with_current_head_reviewer_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": "2026-03-02T00:00:00Z",
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
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
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_check_overdue_reviews_skips_item_when_snapshot_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: None)

    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_handle_overdue_review_warning_only_records_successful_comment(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: False)

    assert reviewer_bot.maintenance_module.handle_overdue_review_warning(reviewer_bot, state, 42, "alice") is False
    assert review["transition_warning_sent"] is None


def test_check_overdue_reviews_uses_contributor_comment_timestamp_when_turn_returns_to_reviewer(monkeypatch):
    now = reviewer_bot.datetime.now(reviewer_bot.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 19))
    contributor_comment_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS, minutes=1))
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = assigned_at
    review["active_cycle_started_at"] = assigned_at
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": reviewer_review_at,
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_comment"]["accepted"] = {
        "semantic_key": "issue_comment:20",
        "timestamp": contributor_comment_at,
        "actor": "bob",
        "reviewed_head_sha": None,
        "source_precedence": 0,
        "payload": {},
    }
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
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    overdue = reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_uses_contributor_revision_timestamp_when_head_changes_after_review(monkeypatch):
    now = reviewer_bot.datetime.now(reviewer_bot.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 19))
    contributor_revision_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS, minutes=1))
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = assigned_at
    review["active_cycle_started_at"] = assigned_at
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": reviewer_review_at,
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_revision"]["accepted"] = {
        "semantic_key": "pull_request_sync:42:head-2",
        "timestamp": contributor_revision_at,
        "actor": None,
        "reviewed_head_sha": "head-2",
        "source_precedence": 1,
        "payload": {},
    }
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
    overdue = reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_ignores_same_head_contributor_revision_after_valid_reviewer_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": "2026-03-02T00:00:00Z",
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_revision"]["accepted"] = {
        "semantic_key": "pull_request_head_observed:42:head-1",
        "timestamp": "2026-03-12T00:00:00Z",
        "actor": None,
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
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
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_check_overdue_reviews_uses_live_current_head_review_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-02T00:00:00Z",
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
                "submitted_at": "2026-03-20T00:00:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-21T00:00:00Z",
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

    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []
