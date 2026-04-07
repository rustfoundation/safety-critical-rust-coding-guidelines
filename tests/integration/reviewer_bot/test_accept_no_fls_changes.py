from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from builder import build_cli
from scripts.reviewer_bot_core import privileged_command_policy
from scripts.reviewer_bot_lib import automation
from scripts.reviewer_bot_lib.config import FLS_AUDIT_LABEL
from tests.fixtures.commands_harness import CommandHarness


def test_list_changed_files_ignores_untracked_bootstrap_noise(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    runner = harness.automation_runner()
    runner.when(["git", "diff", "--name-only"], stdout="")
    runner.when(["git", "diff", "--cached", "--name-only"], stdout="")

    assert automation.list_changed_files(tmp_path) == []
    assert [command for command, _cwd, _check in runner.calls] == [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ]

def test_list_changed_files_reports_tracked_changes_only(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    runner = harness.automation_runner()
    runner.when(["git", "diff", "--name-only"], stdout="README.md\nsrc/spec.lock\n")
    runner.when(["git", "diff", "--cached", "--name-only"], stdout="src/spec.lock\n")

    assert automation.list_changed_files(tmp_path) == ["README.md", "src/spec.lock"]

def test_accept_no_fls_changes_honors_explicit_target_repo_root(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_privileged_request(
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        target_repo_root=str(tmp_path),
    )
    harness.stub_permission("granted")
    observed = {"cwd": None}

    def fake_list_changed_files(repo_root):
        observed["cwd"] = repo_root
        return ["README.md"]

    harness.runtime.list_changed_files = fake_list_changed_files

    message, success = harness.handle_accept_no_fls_changes(42, "alice", request=request)

    assert (message, success) == ("❌ Working tree is not clean; refusing to update spec.lock.", False)
    assert observed["cwd"] == tmp_path

def test_accept_no_fls_changes_uses_locked_nested_uv_commands(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_privileged_request(
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        target_repo_root=str(tmp_path),
    )
    harness.stub_permission("granted")
    list_calls = {"count": 0}

    def fake_list_changed_files(repo_root):
        list_calls["count"] += 1
        assert repo_root == tmp_path
        return []

    runner = harness.automation_runner()
    runner.when(["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"])
    runner.when(["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"])

    harness.runtime.list_changed_files = fake_list_changed_files

    message, success = harness.handle_accept_no_fls_changes(42, "alice", request=request)

    assert (message, success) == ("✅ `src/spec.lock` is already up to date; no PR needed.", True)
    assert list_calls["count"] == 2
    assert runner.calls == [
        (["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"], tmp_path, False),
        (["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"], tmp_path, False),
    ]

def test_accept_no_fls_changes_surfaces_locked_uv_failure_details(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_privileged_request(
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        target_repo_root=str(tmp_path),
    )
    harness.stub_permission("granted")
    harness.runtime.list_changed_files = lambda repo_root: []
    runner = harness.automation_runner()
    runner.when(
        ["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        returncode=1,
        stderr="error: lockfile at uv.lock needs to be updated, but --locked was provided",
    )

    message, success = harness.handle_accept_no_fls_changes(42, "alice", request=request)

    assert success is False
    assert "Audit command failed." in message
    assert "--locked was provided" in message

def test_update_spec_lock_file_mode_exits_before_build_docs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        build_cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {
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
            },
        )(),
    )
    called = {"update": 0, "build": 0}
    monkeypatch.setattr(build_cli, "update_spec_lockfile", lambda url, path: called.__setitem__("update", called["update"] + 1) or True)
    monkeypatch.setattr(build_cli, "build_docs", lambda *args, **kwargs: called.__setitem__("build", called["build"] + 1))

    with pytest.raises(SystemExit) as exc_info:
        build_cli.main(tmp_path)

    assert exc_info.value.code == 0
    assert called == {"update": 1, "build": 0}


def test_accept_no_fls_changes_freezes_ordered_execution_plan_branch_name_and_pr_metadata(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_privileged_request(
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
        is_pull_request=False,
        issue_labels=(FLS_AUDIT_LABEL,),
        target_repo_root=str(tmp_path),
    )
    harness.stub_permission("granted")
    list_calls = {"count": 0}
    observed = {}

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 4, 6, 12, 34, 56, tzinfo=timezone.utc)

    def fake_list_changed_files(repo_root):
        list_calls["count"] += 1
        return [] if list_calls["count"] == 1 else ["src/spec.lock"]

    runner = harness.automation_runner()
    runner.when(["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"])
    runner.when(["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"])
    runner.when(["git", "rev-parse", "--verify", "chore/spec-lock-2026-04-06-issue-42"], returncode=1)
    runner.when(["git", "checkout", "-b", "chore/spec-lock-2026-04-06-issue-42"])
    runner.when(["git", "add", "src/spec.lock"])
    runner.when([
        "git",
        "-c",
        "user.name=guidelines-bot",
        "-c",
        "user.email=guidelines-bot@users.noreply.github.com",
        "commit",
        "-m",
        "chore: update spec.lock; no affected guidelines",
    ])
    runner.when(["git", "push", "origin", "chore/spec-lock-2026-04-06-issue-42"])

    monkeypatch.setattr(automation, "datetime", FrozenDateTime)
    harness.runtime.list_changed_files = fake_list_changed_files
    harness.runtime.get_default_branch = lambda: "main"
    monkeypatch.setattr(
        automation,
        "create_pull_request",
        lambda bot, branch, base, issue_number, title=None, body=None: observed.update(
            {"branch": branch, "base": base, "issue_number": issue_number, "title": title, "body": body}
        ) or {"html_url": "https://example.invalid/pr/1"},
    )

    message, success = harness.handle_accept_no_fls_changes(42, "alice", request=request)

    assert (message, success) == ("✅ Opened PR https://example.invalid/pr/1", True)
    assert observed == {
        "branch": "chore/spec-lock-2026-04-06-issue-42",
        "base": "main",
        "issue_number": 42,
        "title": "chore: update spec.lock (no guideline impact)",
        "body": "Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\nCloses #42",
    }
    assert [command for command, _cwd, _check in runner.calls] == [
        ["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        ["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"],
        ["git", "rev-parse", "--verify", "chore/spec-lock-2026-04-06-issue-42"],
        ["git", "checkout", "-b", "chore/spec-lock-2026-04-06-issue-42"],
        ["git", "add", "src/spec.lock"],
        [
            "git",
            "-c",
            "user.name=guidelines-bot",
            "-c",
            "user.email=guidelines-bot@users.noreply.github.com",
            "commit",
            "-m",
            "chore: update spec.lock; no affected guidelines",
        ],
        ["git", "push", "origin", "chore/spec-lock-2026-04-06-issue-42"],
    ]


def test_j1_executor_consumes_richer_plan_command_lists_without_rederiving_git_steps(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    plan = privileged_command_policy.AcceptNoFlsChangesPlan(
        ordered_steps=list(privileged_command_policy.ORDERED_EXECUTION_STEPS),
        revalidation_checkpoints=list(privileged_command_policy.REVALIDATION_CHECKPOINTS),
        expected_changed_files=["src/spec.lock"],
        branch_probe_name="chore/spec-lock-2026-04-06-issue-42",
        branch_name="chore/spec-lock-2026-04-06-issue-42",
        base_branch="main",
        add_paths=["src/spec.lock"],
        git_checkout_args=["git", "checkout", "-b", "chore/spec-lock-2026-04-06-issue-42"],
        git_commit_args=[
            "git",
            "-c",
            "user.name=guidelines-bot",
            "-c",
            "user.email=guidelines-bot@users.noreply.github.com",
            "commit",
            "-m",
            "chore: update spec.lock; no affected guidelines",
        ],
        git_push_args=["git", "push", "origin", "chore/spec-lock-2026-04-06-issue-42"],
        commit_message="chore: update spec.lock; no affected guidelines",
        pull_request_title="chore: update spec.lock (no guideline impact)",
        pull_request_body="Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\nCloses #42",
    )
    runner = harness.automation_runner()
    runner.when(plan.git_checkout_args)
    runner.when(["git", "add", "src/spec.lock"])
    runner.when(plan.git_commit_args)
    runner.when(plan.git_push_args)
    monkeypatch.setattr(
        automation,
        "create_pull_request",
        lambda bot, branch, base, issue_number, title=None, body=None: {"html_url": "https://example.invalid/pr/2"},
    )

    message, success = automation._execute_accept_no_fls_changes_plan(harness.runtime, tmp_path, 42, plan)

    assert (message, success) == ("✅ Opened PR https://example.invalid/pr/2", True)
    assert [command for command, _cwd, _check in runner.calls] == [
        plan.git_checkout_args,
        ["git", "add", "src/spec.lock"],
        plan.git_commit_args,
        plan.git_push_args,
    ]


def test_automation_executor_phase_checklist_and_plan_execution_helper_are_explicit():
    module_text = Path("scripts/reviewer_bot_lib/automation.py").read_text(encoding="utf-8")

    assert "EXECUTOR_PHASE_CHECKLIST = [" in module_text
    assert '"audit_command_execution"' in module_text
    assert '"spec_lock_update_command_execution"' in module_text
    assert '"changed_file_validation_execution"' in module_text
    assert '"branch_existence_check"' in module_text
    assert '"pull_request_create"' in module_text
    assert "def _resolve_accept_no_fls_changes_plan(" in module_text
    assert "def _execute_accept_no_fls_changes_plan(" in module_text
    assert "return _execute_accept_no_fls_changes_plan(bot, repo_root, issue_number, planning.plan)" in module_text
