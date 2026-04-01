import json
import os

import pytest
from factories import make_state

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing, sweeper


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

def test_handle_workflow_run_event_returns_true_for_submitted_review_bookkeeping_only_mutations(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "bob"
    review["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/11":
            return {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "pull_request_review:11" in review["reconciled_source_events"]
    assert "pull_request_review:11" not in review["deferred_gaps"]

def test_handle_workflow_run_event_persists_fail_closed_diagnostic_without_raising(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:12",
                "pr_number": 42,
                "review_id": 12,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "pulls/42/reviews/12":
            return reviewer_bot.GitHubApiResult(
                status_code=502,
                payload={"message": "bad gateway"},
                headers={},
                text="bad gateway",
                ok=False,
                failure_kind="server_error",
                retry_attempts=1,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    gap = review["deferred_gaps"]["pull_request_review:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"

def test_deferred_comment_reconcile_returns_true_for_bookkeeping_only_mutations(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /queue"
    payload_path.write_text(
        json.dumps(
            {
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
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "610")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(reviewer_bot.reconcile_module, "_handle_command", lambda *args, **kwargs: False)

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/210":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "issue_comment:210" in review["reconciled_source_events"]
    assert "issue_comment:210" not in review["deferred_gaps"]

def test_handle_workflow_run_event_rebuilds_completion_from_live_review_commit_id(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    payload_path = tmp_path / "deferred.json"
    payload_path.write_text(
        json.dumps(
            {
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
                "source_review_state": "APPROVED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"head": {"sha": "head-2"}},
            "pulls/42/reviews/11": {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "APPROVED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "APPROVED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["current_cycle_completion"]["completed"] is False

def test_handle_workflow_run_event_refreshes_stale_stored_reviewer_review_to_current_head_preferred_review(tmp_path, monkeypatch):
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
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 500,
                "source_run_attempt": 2,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:99",
                "pr_number": 42,
                "review_id": 99,
                "source_submitted_at": "2026-03-17T11:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-0",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/99":
            return {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"

def test_deferred_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:99",
                "pr_number": 42,
                "comment_id": 99,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: (
            {"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None
        ),
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"]["semantic_key"] == "issue_comment:99"
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:99"]["reason"] == "reconcile_failed_closed"

def test_deferred_review_comment_reconcile_records_contributor_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "author reply in review thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 701,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:301",
                "pr_number": 42,
                "comment_id": 301,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
                "actor_id": 5,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-701-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "701")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/301":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["contributor_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:301"

def test_deferred_review_comment_reconcile_records_reviewer_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "reviewer reply in thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 702,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:302",
                "pr_number": 42,
                "comment_id": 302,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T11:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-702-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "702")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/302":
            return {
                "body": live_body,
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:302"

def test_deferred_review_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 703,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:303",
                "pr_number": 42,
                "comment_id": 303,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-703-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "703")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: ({"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None),
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:303"
    assert review["deferred_gaps"]["pull_request_review_comment:303"]["reason"] == "reconcile_failed_closed"

def test_review_comment_artifact_identity_validation(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 704,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:304",
                "pr_number": 42,
                "comment_id": 304,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-704-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "704")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(reviewer_bot, "github_api", lambda method, endpoint, data=None: {"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None)
    assert reviewer_bot.handle_workflow_run_event(state) is True

def test_deferred_comment_reconcile_hydrates_pr_author_context_for_contributor_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 601,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:199",
                "pr_number": 42,
                "comment_id": 199,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "601")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/199":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:199"
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"] is None
    assert os.environ["IS_PULL_REQUEST"] == "true"
    assert os.environ["ISSUE_AUTHOR"] == "dana"
    assert json.loads(os.environ["ISSUE_LABELS"]) == ["coding guideline"]

def test_deferred_comment_reconcile_uses_pr_assignment_semantics_for_claim(tmp_path, monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "bob", "name": "Bob"}]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /claim"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 602,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:200",
                "pr_number": 42,
                "comment_id": 200,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "602")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    assignment_calls = []
    removed_reviewers = []
    posted_comments = []

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {
                "user": {"login": "dana"},
                "labels": [{"name": "coding guideline"}],
                "requested_reviewers": [{"login": "alice"}],
            }
        if endpoint == "issues/comments/200":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    def fake_request(issue_number, username):
        assignment_calls.append(
            {
                "issue_number": issue_number,
                "username": username,
                "is_pull_request": os.environ.get("IS_PULL_REQUEST"),
                "issue_author": os.environ.get("ISSUE_AUTHOR"),
            }
        )
        return reviewer_bot.AssignmentAttempt(success=True, status_code=201)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", fake_request)
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda issue_number, username: removed_reviewers.append((issue_number, username)) or True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted_comments.append((issue_number, body)) or True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert assignment_calls == [
        {
            "issue_number": 42,
            "username": "bob",
            "is_pull_request": "true",
            "issue_author": "dana",
        }
    ]
    assert removed_reviewers == [(42, "alice")]
    assert state["active_reviews"]["42"]["current_reviewer"] == "bob"
    assert posted_comments

def test_deferred_comment_reconcile_fails_closed_when_command_replay_is_ambiguous(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /claim"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 603,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:201",
                "pr_number": 42,
                "comment_id": 201,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "603")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/201":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )
    command_calls = []
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_handle_command",
        lambda *args, **kwargs: command_calls.append("called") or True,
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert command_calls == []
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:201" not in state["active_reviews"]["42"]["reconciled_source_events"]

def test_validate_live_comment_replay_contract_reports_changed_for_command_ambiguity(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    payload = {
        "comment_id": 201,
        "comment_class": "command_only",
        "has_non_command_text": False,
        "source_event_key": "issue_comment:201",
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_created_at": "2026-03-17T10:00:00Z",
        "pr_number": 42,
        "source_run_id": 603,
        "source_run_attempt": 1,
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_artifact_name": "reviewer-bot-comment-context-603-attempt-1",
    }
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )

    result = reviewer_bot.reconcile_module._validate_live_comment_replay_contract(
        reviewer_bot,
        review,
        payload,
        "@guidelines-bot /claim",
    )

    assert result.live_classified is None
    assert result.changed is True
    assert result.failed_closed is True
    assert review["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"

def test_deferred_comment_reconcile_records_failure_kind_when_live_comment_unavailable(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment-unavailable.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 603,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:205",
                "pr_number": 42,
                "comment_id": 205,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "603")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"user": {"login": "dana"}, "labels": []},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "issues/comments/205":
            return reviewer_bot.GitHubApiResult(
                status_code=502,
                payload={"message": "bad gateway"},
                headers={},
                text="bad gateway",
                ok=False,
                failure_kind="server_error",
                retry_attempts=1,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    gap = state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:205"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"

def test_deferred_comment_reconcile_fails_closed_when_comment_classification_drifts(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 604,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:202",
                "pr_number": 42,
                "comment_id": 202,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "604")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/202":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_plus_text",
            "has_non_command_text": True,
            "command_count": 1,
            "command": "claim",
            "args": [],
            "normalized_body": body,
        },
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:202"
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:202"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:202" not in state["active_reviews"]["42"]["reconciled_source_events"]

def test_execute_pending_privileged_command_revalidates_live_state(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "handle_accept_no_fls_changes_command", lambda issue_number, actor: ("ok", True))
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

def test_execute_pending_privileged_command_hydrates_issue_labels_for_executor(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.delenv("ISSUE_LABELS", raising=False)
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)

    observed = {}

    def fake_handle(issue_number, actor):
        observed["issue_number"] = issue_number
        observed["actor"] = actor
        observed["issue_labels"] = json.loads(os.environ["ISSUE_LABELS"])
        return ("ok", True)

    monkeypatch.setattr(reviewer_bot, "handle_accept_no_fls_changes_command", fake_handle)
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert observed == {
        "issue_number": 42,
        "actor": "alice",
        "issue_labels": [reviewer_bot.FLS_AUDIT_LABEL],
    }
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

def test_execute_pending_privileged_command_fails_closed_without_live_fls_audit_label(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": "status: awaiting reviewer response"}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    called = {"handle": 0}
    monkeypatch.setattr(
        reviewer_bot,
        "handle_accept_no_fls_changes_command",
        lambda issue_number, actor: called.__setitem__("handle", called["handle"] + 1) or ("ok", True),
    )
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert called["handle"] == 0
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_revalidation_failed"

def test_resolve_workflow_run_pr_number_fails_closed_when_pr_unavailable(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "42")
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "head-1")
    monkeypatch.setenv("WORKFLOW_RUN_HEAD_SHA", "head-1")
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

    with pytest.raises(RuntimeError, match="Failed to fetch pull request #42 during workflow_run reconcile"):
        reviewer_bot.resolve_workflow_run_pr_number()

def test_sweeper_skips_dismissed_reviews_already_reconciled_by_source_event_key(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["pull_request_review_dismissed:303"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 303, "submitted_at": "2026-03-17T09:00:00Z", "updated_at": "2026-03-17T12:00:00Z", "state": "DISMISSED"},
        ],
    )
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}

def test_sweeper_skips_events_already_reconciled_by_source_event_key(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["issue_comment:101", "pull_request_review:202"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-17T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [{"id": 202, "submitted_at": "2026-03-17T11:00:00Z", "state": "APPROVED"}])
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


@pytest.mark.parametrize(
    ("payload", "workflow_name", "workflow_file", "artifact_name", "payload_name"),
    [
        (
            {"source_event_name": "issue_comment", "source_event_action": "created", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-1-attempt-2",
            "deferred-comment.json",
        ),
        (
            {"source_event_name": "pull_request_review", "source_event_action": "submitted", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-1-attempt-2",
            "deferred-review-submitted.json",
        ),
        (
            {"source_event_name": "pull_request_review", "source_event_action": "dismissed", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-1-attempt-2",
            "deferred-review-dismissed.json",
        ),
        (
            {"source_event_name": "pull_request_review_comment", "source_event_action": "created", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-1-attempt-2",
            "deferred-review-comment.json",
        ),
    ],
)
def test_deferred_workflow_identity_helpers_match_expected_contract(
    payload,
    workflow_name,
    workflow_file,
    artifact_name,
    payload_name,
):
    assert reviewer_bot.reconcile_module._expected_observer_identity(payload) == (
        workflow_name,
        workflow_file,
    )
    assert reviewer_bot.reconcile_module._artifact_expected_name(payload) == artifact_name
    assert reviewer_bot.reconcile_module._artifact_expected_payload_name(payload) == payload_name

def test_validate_workflow_run_artifact_identity_rejects_triggering_name_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Wrong Workflow")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="Triggering workflow name mismatch"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)

def test_validate_workflow_run_artifact_identity_rejects_run_attempt_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="run_attempt mismatch"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)

def test_validate_workflow_run_artifact_identity_requires_successful_conclusion(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "failure")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="did not conclude successfully"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)
