
import pytest

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing
from tests.fixtures.commands_harness import CommandHarness
from tests.fixtures.reviewer_bot import make_state


def test_label_signoff_create_pr_marks_issue_review_complete_without_inline_status_sync(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.set_comment_command(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /label +sign-off: create pr",
        issue_author="dana",
        is_pull_request=False,
    )
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda *args, **kwargs: pytest.fail("status sync should run only from app orchestration after save"),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    posted = harness.record_comments()

    assert reviewer_bot.handle_comment_event(state) is True
    assert review["review_completion_source"] == "issue_label: sign-off: create pr"
    assert review["current_cycle_completion"]["completed"] is True
    assert posted == [(42, "✅ Added label `sign-off: create pr`")]


def test_label_signoff_create_pr_on_pr_does_not_mark_issue_complete(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.set_comment_command(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /label +sign-off: create pr",
        issue_author="dana",
        is_pull_request=True,
        author_association="MEMBER",
        workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        repository="rustfoundation/safety-critical-rust-coding-guidelines",
        ref="refs/heads/main",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda *args, **kwargs: pytest.fail("status sync should not run for PR sign-off label command"),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)

    assert reviewer_bot.handle_comment_event(state) is False
    assert review["review_completion_source"] is None


def test_create_pull_request_fails_closed_when_open_pr_lookup_unavailable(monkeypatch):
    called = {"post": 0}
    monkeypatch.setattr(reviewer_bot, "find_open_pr_for_branch_status", lambda branch: ("unavailable", None))
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: called.__setitem__("post", called["post"] + 1) or None,
    )

    with pytest.raises(RuntimeError, match="Unable to determine whether branch 'feature-branch' already has an open PR"):
        reviewer_bot.create_pull_request("feature-branch", "main", 42)

    assert called["post"] == 0


def test_assign_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_command_posts_pr_guidance_on_success(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    harness.set_assignment_context(issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")

    assert success is True
    assert response == "✅ @felix91gr has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_claim_command_posts_pr_guidance_on_success(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    harness.set_assignment_context(issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    response, success = reviewer_bot.handle_claim_command(state, 42, "felix91gr")

    assert success is True
    assert response == "✅ @felix91gr has claimed this review."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_pass_command_posts_pr_guidance_for_new_reviewer(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [
        {"github": "alice", "name": "Alice"},
        {"github": "felix91gr", "name": "Félix Fischer"},
    ]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.set_assignment_context(issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees(["alice"])
    harness.stub_assignment()
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda issue_number, username: True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    response, success = reviewer_bot.handle_pass_command(state, 42, "alice", None)

    assert success is True
    assert "@felix91gr is now assigned as the reviewer." in response
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_assign_from_queue_posts_guidance_only_once(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    harness.set_assignment_context(issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)

    assert success is True
    assert response == "✅ @felix91gr (next in queue) has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_handle_accept_no_fls_changes_command_fails_closed_when_permission_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    harness.set_privileged_context(labels=[reviewer_bot.FLS_AUDIT_LABEL], is_pull_request=False)
    harness.stub_permission("unavailable")

    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")

    assert success is False
    assert "Unable to verify triage permissions right now" in message


def test_pass_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_pass_command(state, 42, "alice", None)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_away_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}, {"github": "bob", "name": "Bob"}]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_pass_until_command(
        state,
        42,
        "alice",
        "2099-01-01",
        None,
    )

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_claim_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_claim_command(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_release_command_fails_closed_when_permission_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    response, success = reviewer_bot.handle_release_command(state, 42, "alice", ["@bob"])

    assert success is False
    assert "Unable to verify triage permissions right now" in response


def test_release_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_release_command(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_from_queue_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_handle_rectify_command_reports_permission_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "ensure_review_entry", lambda current, issue_number: None)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    message, success, changed = reviewer_bot.handle_rectify_command(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Unable to verify triage permissions right now" in message


def test_handle_rectify_command_reports_permission_denied(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "ensure_review_entry", lambda current, issue_number: None)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "denied")

    message, success, changed = reviewer_bot.handle_rectify_command(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Only maintainers with triage+ permission" in message


def test_validate_accept_no_fls_changes_handoff_distinguishes_permission_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    ok, metadata = comment_routing._validate_accept_no_fls_changes_handoff(
        reviewer_bot,
        42,
        "alice",
    )

    assert ok is False
    assert metadata["reason"] == "authorization_unavailable"


def test_manual_dispatch_marks_live_permission_unavailable_for_pending_privileged_command(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"] = {
        "issue_comment:100": {
            "source_event_key": "issue_comment:100",
            "command_name": "accept-no-fls-changes",
            "issue_number": 42,
            "actor": "alice",
            "status": "pending",
        }
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    assert reviewer_bot.handle_manual_dispatch(state) is True
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_permission_unavailable"
