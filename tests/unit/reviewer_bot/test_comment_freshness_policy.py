from types import SimpleNamespace

from scripts.reviewer_bot_core.comment_freshness_policy import (
    build_comment_freshness_event,
    decide_comment_freshness_event,
)


def _request(**overrides):
    defaults = {
        "issue_number": 264,
        "is_pull_request": True,
        "issue_author": "contributor",
        "comment_id": 123,
        "comment_author": "iglesias",
        "comment_created_at": "2026-04-13T23:23:25Z",
        "comment_source_event_key": "issue_comment:123",
        "comment_source_kind": "issue_comment",
        "reviewed_head_sha": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_plain_current_reviewer_pr_issue_comment_is_diagnostic_only():
    event = build_comment_freshness_event({"current_reviewer": "iglesias"}, _request())

    decision = decide_comment_freshness_event(event, current_head_sha="head-a")

    assert decision.kind == "diagnostic_only"
    assert decision.update_reviewer_activity is False
    assert decision.diagnostic_reason == "plain_pr_reviewer_comment_is_diagnostic_only"


def test_stale_review_comment_cannot_update_current_scope_activity():
    event = build_comment_freshness_event(
        {"current_reviewer": "iglesias"},
        _request(
            comment_source_kind="pull_request_review_comment",
            comment_source_event_key="pull_request_review_comment:123",
            reviewed_head_sha="old-head",
        ),
    )

    decision = decide_comment_freshness_event(event, current_head_sha="new-head")

    assert decision.kind == "diagnostic_only"
    assert decision.update_reviewer_activity is False
    assert decision.diagnostic_reason == "stale_reviewed_head_sha"
