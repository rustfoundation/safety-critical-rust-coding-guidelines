import json
from types import SimpleNamespace

from scripts.reviewer_bot_lib import reviews, reviews_projection
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)


def _bot(**overrides):
    github = SimpleNamespace(
        get_pull_request_reviews=lambda issue_number: [],
        get_issue_or_pr_snapshot=lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
        get_user_permission_status=lambda username, required_permission="push": "granted",
    )
    bot = SimpleNamespace(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(200, {}, {}, "ok", True, None, 0, None),
        github_api=lambda method, endpoint, data=None: {},
        github=github,
        parse_github_timestamp=reviews.parse_github_timestamp,
        parse_iso8601_timestamp=reviews.parse_github_timestamp,
        ensure_review_entry=lambda state, issue_number, create=False: None,
    )
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot


def test_compute_reviewer_response_state_is_pure_for_pr_projection():
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    before = json.loads(json.dumps(review))
    bot = _bot(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request_payload(42, head_sha="head-1") if endpoint == "pulls/42" else [],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
    )

    response_state = reviews.compute_reviewer_response_state(bot, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert review == before


def test_compute_pr_approval_state_result_is_pure():
    review = make_tracked_review_state(
        make_state(),
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    before = json.loads(json.dumps(review))
    bot = _bot(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request_payload(42, head_sha="head-1")
            if endpoint == "pulls/42"
            else [
                review_payload(
                    10,
                    state="APPROVED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="alice",
                )
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
    )

    result = reviews.compute_pr_approval_state_result(bot, 42, review)

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert review == before


def test_apply_pr_approval_state_mutates_expected_fields():
    review = make_tracked_review_state(make_state(), 42)

    reviews.apply_pr_approval_state(
        review,
        completion={"completed": True, "current_head_sha": "head-1", "qualifying_review_ids": [10]},
        write_approval={"has_write_approval": True, "write_approvers": ["alice"], "current_head_sha": "head-1"},
        current_head_sha="head-1",
    )

    assert review["active_head_sha"] == "head-1"
    assert review["current_cycle_completion"]["completed"] is True
    assert review["current_cycle_write_approval"]["has_write_approval"] is True
    assert review["review_completion_source"] == "live_review_rebuild"


def test_compute_pr_approval_state_from_reviews_is_pure():
    survivors = {
        "alice": {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": reviews.parse_github_timestamp("2026-03-17T10:01:00Z"),
            "commit_id": "head-1",
            "user": {"login": "alice"},
        }
    }
    before = json.loads(json.dumps({"survivors": {"alice": {"id": 10, "state": "APPROVED", "commit_id": "head-1", "user": {"login": "alice"}}}}))

    result = reviews_projection.compute_pr_approval_state_from_reviews(
        survivors,
        current_head="head-1",
        permission_statuses={"alice": "granted"},
    )

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert before["survivors"]["alice"]["id"] == 10


def test_normalize_reviews_with_parsed_timestamps_is_pure():
    review_items = [
        {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": "2026-03-17T10:01:00Z",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        }
    ]
    before = json.loads(json.dumps(review_items))

    normalized = reviews_projection.normalize_reviews_with_parsed_timestamps(
        review_items,
        parse_timestamp=reviews.parse_github_timestamp,
    )

    assert normalized[0]["submitted_at"] == reviews.parse_github_timestamp("2026-03-17T10:01:00Z")
    assert review_items == before


def test_collect_permission_statuses_deduplicates_authors():
    survivors = {
        "alice": {"user": {"login": "alice"}},
        "alice-2": {"user": {"login": "alice"}},
        "bob": {"user": {"login": "bob"}},
    }
    observed = []

    statuses = reviews_projection.collect_permission_statuses(
        survivors,
        permission_status=lambda author: observed.append(author) or "granted",
    )

    assert statuses == {"alice": "granted", "bob": "granted"}
    assert observed == ["alice", "bob"]
