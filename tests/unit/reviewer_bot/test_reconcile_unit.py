import pytest

from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


def test_parse_deferred_context_payload_returns_typed_review_payload():
    payload = {
        "schema_version": 2,
        "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        "source_run_id": 500,
        "source_run_attempt": 2,
        "source_event_name": "pull_request_review",
        "source_event_action": "submitted",
        "source_event_key": "pull_request_review:11",
        "pr_number": 42,
        "review_id": 11,
        "source_submitted_at": "2026-03-17T10:00:00Z",
        "source_review_state": "COMMENTED",
        "source_commit_id": "head-1",
        "actor_login": "alice",
    }

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.DeferredReviewPayload)
    assert parsed.identity.source_event_name == "pull_request_review"
    assert parsed.review_id == 11
    assert parsed.pr_number == 42


def test_parse_deferred_context_payload_returns_typed_comment_payload():
    payload = {
        "schema_version": 2,
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": "issue_comment:210",
        "pr_number": 42,
        "comment_id": 210,
        "comment_class": "command_only",
        "has_non_command_text": False,
        "source_body_digest": "abc123",
        "source_created_at": "2026-03-17T10:00:00Z",
        "actor_login": "bob",
    }

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.DeferredCommentPayload)
    assert parsed.identity.source_event_key == "issue_comment:210"
    assert parsed.comment_id == 210


def test_parse_deferred_context_payload_returns_typed_observer_noop_payload():
    payload = {
        "schema_version": 1,
        "kind": "observer_noop",
        "reason": "not a command",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": "issue_comment:210",
        "pr_number": 42,
    }

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.ObserverNoopPayload)
    assert parsed.reason == "not a command"
    assert parsed.pr_number == 42


def test_reconcile_active_review_entry_uses_explicit_head_repair_changed_field(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "refresh_reviewer_review_from_live_preferred_review",
        lambda bot, issue_number, review_data, **kwargs: (False, None),
    )
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )

    message, success, changed = reviewer_bot.reconcile_module.reconcile_active_review_entry(
        reviewer_bot,
        state,
        42,
        require_pull_request_context=True,
    )

    assert success is True
    assert changed is False
    assert "no reconciliation transitions applied" in message


def test_parse_deferred_context_payload_rejects_unsupported_payload():
    with pytest.raises(RuntimeError, match="Unsupported deferred workflow_run payload"):
        reviewer_bot.reconcile_module.parse_deferred_context_payload({"schema_version": 2})
