import json

import pytest

pytestmark = pytest.mark.integration

from scripts import reviewer_bot
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state


def test_handle_non_pr_issue_comment_creates_pending_privileged_command(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    effects = harness.side_effects()
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "granted")

    assert reviewer_bot.comment_routing_module.handle_comment_event(reviewer_bot, state, request) is True
    pending = state["active_reviews"]["42"]["pending_privileged_commands"]
    assert pending["issue_comment:100"]["command_name"] == "accept-no-fls-changes"
    assert pending["issue_comment:100"]["authorization"]["authorized"] is True
    assert effects.comments == [
        (
            42,
            "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. "
            "Use the isolated privileged workflow to execute it from issue `#314` state.",
        )
    ]
    assert effects.reactions == []

def test_closed_non_pr_plain_text_comment_does_not_create_review_entry(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert reviewer_bot.comment_routing_module.handle_comment_event(reviewer_bot, state, request) is False
    assert state["active_reviews"] == {}

def test_closed_non_pr_command_comment_does_not_create_pending_privileged_command(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    effects = harness.side_effects()
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)

    assert reviewer_bot.comment_routing_module.handle_comment_event(reviewer_bot, state, request) is False
    assert state["active_reviews"] == {}
    assert effects.comments == []

def test_closed_non_pr_comment_removes_stale_review_entry(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert reviewer_bot.comment_routing_module.handle_comment_event(reviewer_bot, state, request) is True
    assert "42" not in state["active_reviews"]

def test_closed_non_pr_comment_without_entry_returns_false(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert reviewer_bot.comment_routing_module.handle_comment_event(reviewer_bot, state, request) is False
    assert state["active_reviews"] == {}

def test_open_non_pr_plain_text_comment_still_updates_freshness(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.set_wrapper_env(
        issue_number=42,
        is_pull_request=False,
        issue_state="open",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: contributor plain text comment",
    )

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
