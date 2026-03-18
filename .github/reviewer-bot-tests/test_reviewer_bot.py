import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing, sweeper


def make_state(epoch: str = "freshness_v15"):
    return {
        "schema_version": reviewer_bot.STATE_SCHEMA_VERSION,
        "freshness_runtime_epoch": epoch,
        "last_updated": None,
        "current_index": 0,
        "queue": [],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    keys = [
        "EVENT_NAME",
        "EVENT_ACTION",
        "ISSUE_NUMBER",
        "ISSUE_AUTHOR",
        "IS_PULL_REQUEST",
        "COMMENT_BODY",
        "COMMENT_AUTHOR",
        "COMMENT_ID",
        "COMMENT_CREATED_AT",
        "COMMENT_USER_TYPE",
        "COMMENT_AUTHOR_ASSOCIATION",
        "COMMENT_SENDER_TYPE",
        "COMMENT_INSTALLATION_ID",
        "COMMENT_PERFORMED_VIA_GITHUB_APP",
        "CURRENT_WORKFLOW_FILE",
        "GITHUB_REPOSITORY",
        "GITHUB_REF",
        "ISSUE_BODY",
        "ISSUE_UPDATED_AT",
        "ISSUE_CHANGES_TITLE_FROM",
        "ISSUE_CHANGES_BODY_FROM",
        "SENDER_LOGIN",
        "DEFERRED_CONTEXT_PATH",
        "DEFERRED_ARTIFACT_RETENTION_DAYS",
        "WORKFLOW_RUN_TRIGGERING_NAME",
        "WORKFLOW_RUN_TRIGGERING_ID",
        "WORKFLOW_RUN_TRIGGERING_ATTEMPT",
        "WORKFLOW_RUN_TRIGGERING_CONCLUSION",
        "MANUAL_ACTION",
        "PRIVILEGED_SOURCE_EVENT_KEY",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", object())


def test_load_state_sets_schema_and_epoch_defaults(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "get_state_issue", lambda: {"body": "queue: []\n"})
    state = reviewer_bot.load_state()
    assert state["schema_version"] == reviewer_bot.STATE_SCHEMA_VERSION
    assert state["freshness_runtime_epoch"] == reviewer_bot.FRESHNESS_RUNTIME_EPOCH_LEGACY


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMMENT_USER_TYPE": "Bot", "COMMENT_AUTHOR": "dependabot[bot]"}, "bot_account"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice", "COMMENT_INSTALLATION_ID": "7"}, "github_app_or_other_automation"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice"}, "repo_user_principal"),
        ({"COMMENT_AUTHOR": "mystery"}, "unknown_actor"),
    ],
)
def test_classify_issue_comment_actor(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert comment_routing.classify_issue_comment_actor() == expected


def test_classify_comment_payload_distinguishes_command_plus_text():
    payload = comment_routing.classify_comment_payload(reviewer_bot, "hello\n@guidelines-bot /queue")
    assert payload["comment_class"] == "command_plus_text"
    assert payload["has_non_command_text"] is True


def test_route_issue_comment_trust_allows_only_same_repo_repo_user_principal(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "carol"},
        },
    )
    assert comment_routing.route_issue_comment_trust(reviewer_bot, 42) == "pr_trusted_direct"


def test_route_issue_comment_trust_fails_closed_for_ambiguous_same_repo(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("COMMENT_USER_TYPE", "")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "carol"},
        },
    )
    with pytest.raises(RuntimeError, match="Ambiguous same-repo PR comment trust posture"):
        comment_routing.route_issue_comment_trust(reviewer_bot, 42)


def test_handle_non_pr_issue_comment_creates_pending_privileged_command(monkeypatch):
    state = make_state()
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /accept-no-fls-changes")
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_comment_event(state) is True
    pending = state["active_reviews"]["42"]["pending_privileged_commands"]
    assert pending["issue_comment:100"]["command_name"] == "accept-no-fls-changes"
    assert pending["issue_comment:100"]["authorization"]["authorized"] is True


def test_closed_non_pr_plain_text_comment_does_not_create_review_entry(monkeypatch):
    state = make_state()
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: close comment")
    assert reviewer_bot.handle_comment_event(state) is False
    assert state["active_reviews"] == {}


def test_closed_non_pr_command_comment_does_not_create_pending_privileged_command(monkeypatch):
    state = make_state()
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /accept-no-fls-changes")
    called = {"post_comment": 0}
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: called.__setitem__("post_comment", called["post_comment"] + 1) or True)
    assert reviewer_bot.handle_comment_event(state) is False
    assert state["active_reviews"] == {}
    assert called["post_comment"] == 0


def test_closed_non_pr_comment_removes_stale_review_entry(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: close comment")
    assert reviewer_bot.handle_comment_event(state) is False
    assert "42" not in state["active_reviews"]


def test_open_non_pr_plain_text_comment_still_updates_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "open")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: contributor plain text comment")
    assert reviewer_bot.handle_comment_event(state) is True
    accepted = state["active_reviews"]["42"]["contributor_comment"]["accepted"]
    assert accepted["semantic_key"] == "issue_comment:100"


def test_pr_comment_direct_path_is_epoch_gated(monkeypatch):
    state = make_state(epoch="legacy_v14")
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    assert reviewer_bot.handle_comment_event(state) is False


def test_issue_edit_by_author_records_contributor_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("SENDER_LOGIN", "dana")
    monkeypatch.setenv("ISSUE_TITLE", "New title")
    monkeypatch.setenv("ISSUE_BODY", "body")
    monkeypatch.setenv("ISSUE_CHANGES_TITLE_FROM", "Old title")
    monkeypatch.setenv("ISSUE_CHANGES_BODY_FROM", "body")
    monkeypatch.setenv("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    assert reviewer_bot.handle_issue_edited_event(state) is True
    accepted = review["contributor_comment"]["accepted"]
    assert accepted["semantic_key"].startswith("issues_edit_title:42:")


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
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


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

    def fake_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}}
        return None

    monkeypatch.setattr(reviewer_bot, "github_api", fake_api)
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "APPROVED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "bob"},
            }
        ],
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": False)
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}
    assert metadata["state"] == "awaiting_write_approval"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels_again == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}


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

    assert reviewer_bot.handle_workflow_run_event(state) is False
    assert command_calls == []
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:201" not in state["active_reviews"]["42"]["reconciled_source_events"]


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


def test_observer_noop_payload_is_safe_noop(tmp_path, monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    payload_path = tmp_path / "observer-noop.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "observer_noop",
                "reason": "ignored_non_human_automation",
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 777,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:111",
                "pr_number": 42,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "777")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    assert reviewer_bot.handle_workflow_run_event(state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


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


def test_list_changed_files_ignores_untracked_bootstrap_noise(monkeypatch, tmp_path):
    commands_seen = []

    def fake_run_command(command, cwd, check=True):
        commands_seen.append(command)
        if command == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command == ["git", "diff", "--cached", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(reviewer_bot.automation_module, "run_command", fake_run_command)
    assert reviewer_bot.automation_module.list_changed_files(tmp_path) == []
    assert commands_seen == [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]


def test_list_changed_files_reports_tracked_changes_only(monkeypatch, tmp_path):
    def fake_run_command(command, cwd, check=True):
        if command == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="README.md\nsrc/spec.lock\n", stderr="")
        if command == ["git", "diff", "--cached", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="src/spec.lock\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(reviewer_bot.automation_module, "run_command", fake_run_command)
    assert reviewer_bot.automation_module.list_changed_files(tmp_path) == ["README.md", "src/spec.lock"]


def test_privileged_commands_workflow_executes_source_entrypoint():
    workflow_text = Path(".github/workflows/reviewer-bot-privileged-commands.yml").read_text(encoding="utf-8")
    assert "run: uv run python scripts/reviewer_bot.py" in workflow_text


def test_observer_run_reason_mapping_and_near_miss_signature():
    signature = {"status": "waiting", "conclusion": None, "name": "approval_pending"}
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "approval_pending"}, signature) == "awaiting_observer_approval"
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "almost"}, signature) == "observer_state_unknown"


def test_negative_missing_run_requires_full_scan_and_recheck():
    gap = {
        "source_event_created_at": "2026-03-15T00:00:00Z",
        "full_scan_complete": True,
        "later_recheck_complete": True,
        "correlated_run_found": False,
        "approval_pending_evidence_retained": False,
    }
    assert sweeper.can_mark_observer_run_missing(gap) is True
    gap["later_recheck_complete"] = False
    assert sweeper.can_mark_observer_run_missing(gap) is False


def test_stage_a_candidate_run_correlation_is_exact_to_workflow_event_pr_and_window():
    os.environ["GITHUB_REPOSITORY"] = "rustfoundation/safety-critical-rust-coding-guidelines"
    result = sweeper.correlate_candidate_observer_runs(
        "issue_comment:101",
        source_event_kind="issue_comment:created",
        source_event_created_at="2026-03-17T10:00:00Z",
        pr_number=42,
        workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
        workflow_runs=[
            {
                "id": 1,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:05:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
            {
                "id": 2,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:40:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
        ],
    )
    assert result["candidate_run_ids"] == [1]


def test_stage_b_artifact_correlation_rejects_ambiguous_exact_matches():
    result = sweeper.correlate_run_artifacts_exact(
        {
            10: [{"source_event_key": "issue_comment:101", "source_run_id": 10, "source_run_attempt": 1, "pr_number": 42}],
            11: [{"source_event_key": "issue_comment:101", "source_run_id": 11, "source_run_attempt": 1, "pr_number": 42}],
        },
        "issue_comment:101",
        pr_number=42,
    )
    assert result["status"] == "observer_state_unknown"
    assert result["reason"] == "ambiguous_exact_artifact_matches"


def test_evaluate_gap_state_only_emits_missing_after_negative_inference_contract():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {
            "source_event_created_at": "2026-03-15T00:00:00Z",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run_found": False,
            "approval_pending_evidence_retained": False,
        },
        {
            "status": "no_candidate_runs",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run": None,
        },
        None,
        None,
    )
    assert reason == "observer_run_missing"
    assert diagnostic == "negative_inference_satisfied"


def test_evaluate_gap_state_completed_success_without_exact_artifact_is_artifact_missing():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "reason": "no_exact_source_event_key_match"},
    )
    assert reason == "artifact_missing"
    assert diagnostic == "no_exact_source_event_key_match"


def test_evaluate_gap_state_completed_success_with_expired_artifact_marks_artifact_expired():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "artifact_scan_outcomes": {10: "expired"}},
    )
    assert reason == "artifact_expired"
    assert diagnostic == "prior_visibility_or_retention_proof_required"


def test_artifact_gap_reason_requires_prior_visibility_or_documented_retention():
    expired = {
        "artifact_seen_at": "2026-03-10T00:00:00Z",
        "run_created_at": "2026-03-10T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(expired) == "artifact_expired"
    missing = {
        "artifact_inspection_complete": True,
        "run_created_at": "2026-03-17T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(missing) == "artifact_missing"


def test_sweeper_creates_keyed_deferred_gaps_for_visible_comments_reviews_and_dismissals(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-17T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 202, "submitted_at": "2026-03-17T11:00:00Z", "state": "APPROVED"},
            {"id": 303, "submitted_at": "2026-03-17T09:00:00Z", "updated_at": "2026-03-17T12:00:00Z", "state": "DISMISSED"},
        ],
    )
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "issue_comment:101" in gaps
    assert "pull_request_review:202" in gaps
    assert "pull_request_review_dismissed:303" in gaps
    assert gaps["pull_request_review_dismissed:303"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"


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


def test_workflow_policy_split_and_lock_only_boundaries():
    workflows_dir = Path(".github/workflows")
    required = {
        "reviewer-bot-issues.yml",
        "reviewer-bot-issue-comment-direct.yml",
        "reviewer-bot-sweeper-repair.yml",
        "reviewer-bot-pr-metadata.yml",
        "reviewer-bot-pr-comment-trusted.yml",
        "reviewer-bot-pr-comment-observer.yml",
        "reviewer-bot-pr-review-submitted-observer.yml",
        "reviewer-bot-pr-review-dismissed-observer.yml",
        "reviewer-bot-reconcile.yml",
        "reviewer-bot-privileged-commands.yml",
    }
    assert required.issubset({path.name for path in workflows_dir.glob("reviewer-bot-*.yml")})
    for path in required:
        data = yaml.safe_load((workflows_dir / path).read_text(encoding="utf-8"))
        jobs = data.get("jobs", {})
        for job in jobs.values():
            permissions = job.get("permissions", {})
            steps = job.get("steps", [])
            uses_values = [step.get("uses", "") for step in steps if isinstance(step, dict)]
            text = (workflows_dir / path).read_text(encoding="utf-8")
            if "observer" in path:
                assert permissions.get("contents") == "read"
                assert all("checkout" not in value for value in uses_values)
            if permissions.get("contents") == "write" and path != "reviewer-bot-privileged-commands.yml":
                assert all("checkout" not in value for value in uses_values)
                assert "Temporary lock debt" in text
            for value in uses_values:
                if value:
                    assert "@" in value and len(value.split("@", 1)[1]) == 40


def test_workflow_summaries_and_runbook_references_exist():
    runbook = Path("docs/reviewer-bot-review-freshness-operator-runbook.md")
    assert runbook.exists()
    reconcile = Path(".github/workflows/reviewer-bot-reconcile.yml").read_text(encoding="utf-8")
    assert "docs/reviewer-bot-review-freshness-operator-runbook.md" in reconcile


def test_trusted_pr_comment_workflow_preflights_same_repo_before_mutation():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8"))
    job = data["jobs"]["reviewer-bot-pr-comment-trusted"]
    steps = job["steps"]
    assert steps[0]["name"] == "Decide whether same-repo trusted path applies"
    assert steps[1]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[2]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[3]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[4]["name"] == "Trusted path skipped"
    assert steps[4]["if"] == "env.RUN_TRUSTED_PR_COMMENT != 'true'"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8")
    assert "https://api.github.com/repos/{repo}/pulls/{pr_number}" in workflow_text
    assert "RUN_TRUSTED_PR_COMMENT" in workflow_text


def test_issue_comment_direct_workflow_exports_issue_state():
    workflow_text = Path(".github/workflows/reviewer-bot-issue-comment-direct.yml").read_text(encoding="utf-8")
    assert "ISSUE_STATE: ${{ github.event.issue.state }}" in workflow_text


def test_mutating_reviewer_bot_workflows_do_not_share_global_github_concurrency():
    workflow_paths = [
        ".github/workflows/reviewer-bot-issues.yml",
        ".github/workflows/reviewer-bot-issue-comment-direct.yml",
        ".github/workflows/reviewer-bot-sweeper-repair.yml",
        ".github/workflows/reviewer-bot-pr-metadata.yml",
        ".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        ".github/workflows/reviewer-bot-reconcile.yml",
        ".github/workflows/reviewer-bot-privileged-commands.yml",
    ]
    for workflow_path in workflow_paths:
        data = yaml.safe_load(Path(workflow_path).read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            assert "concurrency" not in job


def test_classify_event_intent_treats_supported_workflow_run_sources_as_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING


def test_main_records_repair_needed_when_projection_fails(monkeypatch, tmp_path):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "plain text")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        return json.loads(json.dumps(state))

    def fake_save_state(updated_state):
        saved_states.append(json.loads(json.dumps(updated_state)))
        state.clear()
        state.update(json.loads(json.dumps(updated_state)))
        return True

    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "save_state", fake_save_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None})
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current_state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    reviewer_bot.app_module.main(reviewer_bot)
    assert state["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"
    assert len(saved_states) >= 2
