import json

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import reviews_projection
from tests.fixtures.reviewer_bot import make_state


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


def test_compute_pr_approval_state_from_reviews_is_pure():
    survivors = {
        "alice": {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": reviewer_bot.parse_github_timestamp("2026-03-17T10:01:00Z"),
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
