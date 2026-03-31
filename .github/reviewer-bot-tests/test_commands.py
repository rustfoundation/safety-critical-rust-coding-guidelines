import json
import subprocess
from pathlib import Path

import pytest
from factories import make_state

from builder import build_cli
from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing


def test_label_signoff_create_pr_marks_issue_review_complete_without_inline_status_sync(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda *args, **kwargs: pytest.fail(
            "status sync should run only from app orchestration after save"
        ),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append((issue_number, body)) or True)
    assert reviewer_bot.handle_comment_event(state) is True
    assert review["review_completion_source"] == "issue_label: sign-off: create pr"
    assert review["current_cycle_completion"]["completed"] is True
    assert posted == [(42, "✅ Added label `sign-off: create pr`")]

def test_label_signoff_create_pr_on_pr_does_not_mark_issue_complete(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")
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
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda *args, **kwargs: pytest.fail("status sync should not run for PR sign-off label command"))
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_comment_event(state) is False
    assert review["review_completion_source"] is None

def test_create_pull_request_fails_closed_when_open_pr_lookup_unavailable(monkeypatch):
    called = {"post": 0}
    monkeypatch.setattr(reviewer_bot, "find_open_pr_for_branch_status", lambda branch: ("unavailable", None))
    monkeypatch.setattr(reviewer_bot, "github_api", lambda method, endpoint, data=None: called.__setitem__("post", called["post"] + 1) or None)

    with pytest.raises(RuntimeError, match="Unable to determine whether branch 'feature-branch' already has an open PR"):
        reviewer_bot.create_pull_request("feature-branch", "main", 42)

    assert called["post"] == 0

def test_assign_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "F\u00e9lix Fischer"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response

def test_assign_command_posts_pr_guidance_on_success(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")
    assert success is True
    assert response == "✅ @felix91gr has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]

def test_claim_command_posts_pr_guidance_on_success(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_claim_command(state, 42, "felix91gr")
    assert success is True
    assert response == "✅ @felix91gr has claimed this review."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]

def test_pass_command_posts_pr_guidance_for_new_reviewer(monkeypatch):
    state = make_state()
    state["queue"] = [
        {"github": "alice", "name": "Alice"},
        {"github": "felix91gr", "name": "Félix Fischer"},
    ]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: ["alice"])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda issue_number, username: True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_pass_command(state, 42, "alice", None)
    assert success is True
    assert "@felix91gr is now assigned as the reviewer." in response
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]

def test_assign_from_queue_posts_guidance_only_once(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)
    assert success is True
    assert response == "✅ @felix91gr (next in queue) has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]

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
    assert "Fetch trusted bot source tarball" in workflow_text
    assert 'REVIEWER_BOT_TARGET_REPO_ROOT: ${{ github.workspace }}' in workflow_text
    assert 'run: uv run --project "$BOT_SRC_ROOT" python "$BOT_SRC_ROOT/scripts/reviewer_bot.py"' in workflow_text

def test_accept_no_fls_changes_honors_explicit_target_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    observed = {"cwd": None}

    def fake_list_changed_files(repo_root):
        observed["cwd"] = repo_root
        return ["README.md"]

    monkeypatch.setattr(reviewer_bot, "list_changed_files", fake_list_changed_files)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert (message, success) == ("❌ Working tree is not clean; refusing to update spec.lock.", False)
    assert observed["cwd"] == tmp_path

def test_accept_no_fls_changes_uses_locked_nested_uv_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    list_calls = {"count": 0}

    def fake_list_changed_files(repo_root):
        list_calls["count"] += 1
        assert repo_root == tmp_path
        return []

    commands = []

    def fake_run_command(command, cwd, check=False):
        commands.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(reviewer_bot, "list_changed_files", fake_list_changed_files)
    monkeypatch.setattr(reviewer_bot, "run_command", fake_run_command)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert (message, success) == ("✅ `src/spec.lock` is already up to date; no PR needed.", True)
    assert list_calls["count"] == 2
    assert commands == [
        (["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"], tmp_path, False),
        (["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"], tmp_path, False),
    ]

def test_accept_no_fls_changes_surfaces_locked_uv_failure_details(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "list_changed_files", lambda repo_root: [])

    def fake_run_command(command, cwd, check=False):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="error: lockfile at uv.lock needs to be updated, but --locked was provided",
        )

    monkeypatch.setattr(reviewer_bot, "run_command", fake_run_command)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert success is False
    assert "Audit command failed." in message
    assert "--locked was provided" in message

def test_update_spec_lock_file_mode_exits_before_build_docs(monkeypatch, tmp_path):
    monkeypatch.setattr(build_cli.argparse.ArgumentParser, "parse_args", lambda self: type("Args", (), {
        "clear": False,
        "offline": False,
        "ignore_spec_lock_diff": False,
        "update_spec_lock_file": True,
        "validate_urls": False,
        "serve": False,
        "check_links": False,
        "xml": False,
        "verbose": False,
        "debug": False,
    })())
    called = {"update": 0, "build": 0}
    monkeypatch.setattr(build_cli, "update_spec_lockfile", lambda url, path: called.__setitem__("update", called["update"] + 1) or True)
    monkeypatch.setattr(build_cli, "build_docs", lambda *args, **kwargs: called.__setitem__("build", called["build"] + 1))
    with pytest.raises(SystemExit) as exc_info:
        build_cli.main(tmp_path)
    assert exc_info.value.code == 0
    assert called == {"update": 1, "build": 0}

def test_handle_accept_no_fls_changes_command_fails_closed_when_permission_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

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
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
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
