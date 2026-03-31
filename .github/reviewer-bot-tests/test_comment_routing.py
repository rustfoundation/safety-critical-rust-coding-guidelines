import json
from pathlib import Path

import pytest
from factories import make_state

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing


def test_record_conversation_freshness_returns_true_when_only_reviewer_activity_changes(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T09:00:00Z",
        actor="alice",
    )
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_SOURCE_EVENT_KEY", "issue_comment:100")

    changed = reviewer_bot.comment_routing_module._record_conversation_freshness(
        reviewer_bot,
        state,
        42,
        "alice",
        100,
        "2026-03-17T10:00:00Z",
    )

    assert changed is True
    assert review["last_reviewer_activity"] == "2026-03-17T10:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMMENT_USER_TYPE": "Bot", "COMMENT_AUTHOR": "reviewer-bot"}, "bot_account"),
        ({"COMMENT_INSTALLATION_ID": "12345"}, "github_app_or_other_automation"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice"}, "repo_user_principal"),
        ({"COMMENT_AUTHOR": "mystery", "COMMENT_USER_TYPE": ""}, "unknown_actor"),
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
    assert reviewer_bot.handle_comment_event(state) is True
    assert "42" not in state["active_reviews"]

def test_closed_non_pr_comment_without_entry_returns_false(monkeypatch):
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

def test_build_pr_comment_observer_payload_marks_trusted_direct_same_repo_as_observer_noop(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "PLeVasseur")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "COLLABORATOR")
    monkeypatch.setenv("COMMENT_SENDER_TYPE", "User")
    monkeypatch.setenv("COMMENT_INSTALLATION_ID", "")
    monkeypatch.setenv("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /r? @felix91gr")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_AUTHOR_ID", "123")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-20T20:48:25Z")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "PLeVasseur"},
        },
    )
    payload = reviewer_bot.build_pr_comment_observer_payload(42)
    assert payload["kind"] == "observer_noop"
    assert payload["reason"] == "trusted_direct_same_repo_human_comment"
    assert payload["source_event_key"] == "issue_comment:100"

def test_issue_comment_direct_workflow_exports_issue_state():
    workflow_text = Path(".github/workflows/reviewer-bot-issue-comment-direct.yml").read_text(encoding="utf-8")
    assert "ISSUE_STATE: ${{ github.event.issue.state }}" in workflow_text
