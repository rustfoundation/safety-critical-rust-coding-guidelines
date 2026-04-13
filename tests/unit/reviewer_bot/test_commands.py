
from pathlib import Path

import pytest

from scripts.reviewer_bot_core import privileged_command_policy
from scripts.reviewer_bot_lib import (
    automation,
    commands,
    comment_application,
    guidance,
    reconcile,
    review_state,
)
from scripts.reviewer_bot_lib.config import FLS_AUDIT_LABEL
from tests.fixtures.commands_harness import CommandHarness
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state


def test_label_signoff_create_pr_marks_issue_review_complete_without_inline_status_sync(monkeypatch):
    harness = CommandHarness(monkeypatch)
    assert harness.github is harness.runtime.github
    assert harness.handlers is harness.runtime.handlers
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /label +sign-off: create pr",
        issue_author="dana",
        is_pull_request=False,
    )
    harness.runtime.get_repo_labels = lambda: ["sign-off: create pr"]
    harness.runtime.add_label = lambda issue_number, label: True
    harness.runtime.sync_status_labels_for_items = lambda *args, **kwargs: pytest.fail(
        "status sync should run only from app orchestration after save"
    )
    harness.runtime.add_reaction = lambda *args, **kwargs: True
    posted = harness.capture_posted_comments()

    assert harness.handle_comment_event(state, request=request) is True
    assert review["review_completion_source"] == "issue_label: sign-off: create pr"
    assert review["current_cycle_completion"]["completed"] is True
    assert posted == [(42, "✅ Added label `sign-off: create pr`")]


def test_label_signoff_create_pr_on_pr_does_not_mark_issue_complete(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /label +sign-off: create pr",
        issue_author="dana",
        is_pull_request=True,
    )
    trust_context = harness.typed_trust_context(
        author_association="MEMBER",
        workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        repository="rustfoundation/safety-critical-rust-coding-guidelines",
        ref="refs/heads/main",
    )
    harness.runtime.github_api = lambda method, endpoint, data=None: {
        "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
        "user": {"login": "dana"},
        "pull_request": {},
    }
    harness.runtime.get_repo_labels = lambda: ["sign-off: create pr"]
    harness.runtime.add_label = lambda issue_number, label: True
    harness.runtime.sync_status_labels_for_items = lambda *args, **kwargs: pytest.fail(
        "status sync should not run for PR sign-off label command"
    )
    harness.runtime.add_reaction = lambda *args, **kwargs: True
    harness.runtime.post_comment = lambda *args, **kwargs: True

    assert harness.handle_comment_event(state, request=request, trust_context=trust_context) is False
    assert review["review_completion_source"] is None


def test_create_pull_request_fails_closed_when_open_pr_lookup_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    called = {"post": 0}
    harness.runtime.set_config_value("REPO_OWNER", "rustfoundation")
    harness.runtime.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: harness.runtime.GitHubApiResult(
        502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
    )
    harness.runtime.github_api = lambda method, endpoint, data=None: called.__setitem__("post", called["post"] + 1) or None

    with pytest.raises(RuntimeError, match="Unable to determine whether branch 'feature-branch' already has an open PR"):
        automation.create_pull_request(harness.runtime, "feature-branch", "main", 42)

    assert called["post"] == 0


def test_assign_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_assign(state, 42, "@felix91gr")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_command_posts_pr_guidance_on_success(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    request = harness.typed_assignment_request(issue_number=42, issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    harness.runtime.post_comment = lambda issue_number, body: posted.append(body) or True

    response, success = harness.handle_assign(state, 42, "@felix91gr", request=request)

    assert success is True
    assert response == "✅ @felix91gr has been assigned as reviewer."
    assert posted == [guidance.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_claim_command_posts_pr_guidance_on_success(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    request = harness.typed_assignment_request(issue_number=42, issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    harness.runtime.post_comment = lambda issue_number, body: posted.append(body) or True

    response, success = harness.handle_claim(state, 42, "felix91gr", request=request)

    assert success is True
    assert response == "✅ @felix91gr has claimed this review."
    assert posted == [guidance.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_pass_command_posts_pr_guidance_for_new_reviewer(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [
        {"github": "alice", "name": "Alice"},
        {"github": "felix91gr", "name": "Félix Fischer"},
    ]
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.typed_assignment_request(issue_number=42, issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees(["alice"])
    harness.stub_assignment()
    harness.runtime.unassign_reviewer = lambda issue_number, username: True
    posted = []
    harness.runtime.post_comment = lambda issue_number, body: posted.append(body) or True

    response, success = harness.handle_pass(state, 42, "alice", None, request=request)

    assert success is True
    assert "@felix91gr is now assigned as the reviewer." in response
    assert posted == [guidance.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_assign_from_queue_posts_guidance_only_once(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    request = harness.typed_assignment_request(issue_number=42, issue_author="PLeVasseur", is_pull_request=True)
    harness.stub_assignees([])
    harness.stub_assignment()
    posted = []
    harness.runtime.post_comment = lambda issue_number, body: posted.append(body) or True

    response, success = harness.handle_assign_from_queue(state, 42, request=request)

    assert success is True
    assert response == "✅ @felix91gr (next in queue) has been assigned as reviewer."
    assert posted == [guidance.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_handle_accept_no_fls_changes_command_fails_closed_when_permission_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_privileged_request(
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
    )
    harness.stub_permission("unavailable")

    message, success = harness.handle_accept_no_fls_changes(42, "alice", request=request)

    assert success is False
    assert "Unable to verify triage permissions right now" in message


def test_i1_comment_application_consumes_typed_ordinary_command_result(monkeypatch):
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "ORDINARY_COMMAND_HANDLERS" in module_text
    assert "decision.command_id" in module_text
    assert "decision.needs_assignment_request" in module_text
    assert "CommandExecutionResult" in module_text


def test_k2_comment_application_entrypoints_use_narrow_comment_runtime_protocol():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "CommentApplicationRuntimeContext" in module_text
    assert "bot: CommentApplicationRuntimeContext" in module_text


def test_pass_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_pass(state, 42, "alice", None)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_away_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}, {"github": "bob", "name": "Bob"}]
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_pass_until(state, 42, "alice", "2099-01-01", None)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_claim_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_claim(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_release_command_fails_closed_when_permission_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"

    response, success = harness.handle_release(state, 42, "alice", ["@bob"])

    assert success is False
    assert "Unable to verify triage permissions right now" in response


def test_release_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_release(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_from_queue_command_fails_closed_when_assignees_unavailable(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    harness.runtime.get_issue_assignees = lambda issue_number: None

    response, success = harness.handle_assign_from_queue(state, 42)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_handle_rectify_command_reports_permission_unavailable(monkeypatch):
    state = make_state()
    harness = CommandHarness(monkeypatch)
    monkeypatch.setattr(reconcile, "ensure_review_entry", lambda current, issue_number, create=False: None)
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"

    message, success, changed = harness.handle_rectify(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Unable to verify triage permissions right now" in message


def test_handle_rectify_command_reports_permission_denied(monkeypatch):
    state = make_state()
    harness = CommandHarness(monkeypatch)
    monkeypatch.setattr(reconcile, "ensure_review_entry", lambda current, issue_number, create=False: None)
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "denied"

    message, success, changed = harness.handle_rectify(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Only maintainers with triage+ permission" in message


def test_validate_accept_no_fls_changes_handoff_distinguishes_permission_unavailable(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    harness.runtime.set_config_value("ISSUE_LABELS", f'["{FLS_AUDIT_LABEL}"]')
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )

    decision = privileged_command_policy.validate_accept_no_fls_changes_handoff(
        request,
        "unavailable",
        source_event_key="issue_comment:100",
    )

    assert decision == privileged_command_policy.BlockedPrivilegedHandoff(
        reason="authorization_unavailable",
        response="❌ Unable to verify triage permissions right now; refusing to run this command.",
    )


@pytest.mark.parametrize(
    ("is_pull_request", "labels", "permission", "expected_reason"),
    [
        (True, (FLS_AUDIT_LABEL,), "granted", "pull_request_target_not_allowed"),
        (False, (), "granted", "missing_fls_audit_label"),
        (False, (FLS_AUDIT_LABEL,), "denied", "authorization_failed"),
    ],
)
def test_validate_accept_no_fls_changes_handoff_freezes_fail_closed_reason_matrix(
    monkeypatch,
    is_pull_request,
    labels,
    permission,
    expected_reason,
):
    harness = CommentRoutingHarness(monkeypatch)
    harness.runtime.set_config_value("ISSUE_LABELS", str(list(labels)).replace("'", '"'))
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": permission
    request = harness.request(
        issue_number=42,
        is_pull_request=is_pull_request,
        issue_labels=labels,
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )

    decision = privileged_command_policy.validate_accept_no_fls_changes_handoff(
        request,
        permission,
        source_event_key="issue_comment:100",
    )

    assert decision.reason == expected_reason


def test_validate_accept_no_fls_changes_handoff_freezes_success_metadata_shape(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    harness.runtime.set_config_value("ISSUE_LABELS", f'["{FLS_AUDIT_LABEL}"]')
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )

    decision = privileged_command_policy.validate_accept_no_fls_changes_handoff(
        request,
        "granted",
        source_event_key="issue_comment:100",
    )

    assert decision == privileged_command_policy.AllowedPrivilegedHandoff(
        source_event_key="issue_comment:100",
        command_name=privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value,
        issue_number=42,
        actor="alice",
        authorization_required_permission="triage",
        authorization_authorized=True,
        target_kind="issue",
        target_number=42,
        target_labels_snapshot=(FLS_AUDIT_LABEL,),
    )


def test_apply_comment_command_records_privileged_handoff_side_effects(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    side_effects = harness.capture_comment_side_effects()
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /accept-no-fls-changes",
        issue_author="dana",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
    )
    harness.stub_permission("granted")

    changed = comment_application.apply_comment_command(
        harness.runtime,
        state,
        request,
        {"command": "accept-no-fls-changes", "args": [], "command_count": 1},
        classify_issue_comment_actor=lambda current_request: "repo_user_principal",
    )

    pending = state["active_reviews"]["42"]["sidecars"]["pending_privileged_commands"]["issue_comment:100"]
    assert changed is True
    assert pending["command_name"] == "accept-no-fls-changes"
    assert pending["status"] == "pending"
    assert pending["authorization_authorized"] is True
    assert side_effects.comments == [
        (
            42,
            "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
        )
    ]
    assert side_effects.reactions == []


def test_apply_comment_command_adds_reactions_and_posts_normalized_queue_response(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    side_effects = harness.capture_comment_side_effects()
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /queue",
        issue_author="dana",
        is_pull_request=False,
    )
    monkeypatch.setattr(commands, "handle_queue_command", lambda bot, current_state: ("queue snapshot", True))

    changed = comment_application.apply_comment_command(
        harness.runtime,
        state,
        request,
        {"command": "queue", "args": [], "command_count": 1},
        classify_issue_comment_actor=lambda current_request: "repo_user_principal",
    )

    assert changed is False
    assert side_effects.comments == [(42, "queue snapshot")]
    assert side_effects.reactions == [(100, "eyes"), (100, "+1")]


def test_manual_dispatch_marks_authorization_unavailable_for_pending_privileged_command(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["pending_privileged_commands"] = {
        "issue_comment:100": {
            "source_event_key": "issue_comment:100",
            "command_name": "accept-no-fls-changes",
            "issue_number": 42,
            "actor": "alice",
            "authorization_required_permission": "triage",
            "authorization_authorized": True,
            "target_kind": "issue",
            "target_number": 42,
            "target_labels_snapshot": [FLS_AUDIT_LABEL],
            "status": "pending",
            "created_at": "2026-03-17T10:00:00Z",
        }
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"

    assert harness.handle_manual_dispatch(state) is True
    pending = review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result_code"] == "authorization_unavailable"


@pytest.mark.parametrize(
    ("comment_body", "expected"),
    [
        ("@guidelines-bot /queue", ("queue", [])),
        ("@guidelines-bot /r? producers", ("assign-from-queue", [])),
        ("@guidelines-bot /r? @alice", ("r?-user", ["@alice"])),
        ("@guidelines-bot queue", ("_malformed_known", ["queue"])),
        ("@guidelines-bot /queue\n@guidelines-bot /pass", ("_multiple_commands", [])),
        ("@guidelines-bot hello", None),
    ],
)
def test_parse_command_preserves_known_command_classification(monkeypatch, comment_body, expected):
    harness = CommandHarness(monkeypatch)
    parser_bot = type(
        "ParserBot",
        (),
        {
            "BOT_MENTION": harness.runtime.BOT_MENTION,
            "COMMANDS": {
                "queue",
                "pass",
                "label",
                "away",
                "claim",
                "release",
                "rectify",
                "sync-members",
                "accept-no-fls-changes",
            },
        },
    )()

    assert commands.parse_command(parser_bot, comment_body) == expected


def test_parse_command_preserves_quoted_args(monkeypatch):
    harness = CommandHarness(monkeypatch)

    parser_bot = type("ParserBot", (), {"BOT_MENTION": harness.runtime.BOT_MENTION, "COMMANDS": {"label"}})()

    assert commands.parse_command(parser_bot, '@guidelines-bot /label +"needs decision"') == ("label", ["+needs decision"])


def test_strip_code_blocks_removes_fenced_indented_and_inline_code(monkeypatch):
    comment_body = """before
```bash
@guidelines-bot /queue
```
    @guidelines-bot /queue
inline `@guidelines-bot /queue`
after"""

    assert commands.strip_code_blocks(comment_body) == "before\n\n\ninline \nafter"


def test_comment_application_delegates_ordinary_command_decision_to_core_policy():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "comment_command_policy" in module_text
    assert "decision = comment_command_policy.decide_comment_command(" in module_text


def test_commands_module_exposes_rectify_handler_for_decision_adapter_surface():
    assert hasattr(commands, "handle_rectify_command") is False


def test_comment_application_and_automation_delegate_privileged_planning_to_core_policy():
    comment_application_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")
    automation_text = Path("scripts/reviewer_bot_lib/automation.py").read_text(encoding="utf-8")

    assert "privileged_command_policy" in comment_application_text
    assert "privileged_command_policy.validate_accept_no_fls_changes_handoff(" in comment_application_text
    assert "privileged_command_policy.build_pending_privileged_command(" in comment_application_text
    assert "from scripts.reviewer_bot_core import privileged_command_policy" in automation_text
    assert "privileged_command_policy.prevalidate_accept_no_fls_changes_request(" in automation_text
    assert "privileged_command_policy.plan_accept_no_fls_changes_execution(" in automation_text
