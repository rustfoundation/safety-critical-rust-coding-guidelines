import json
import subprocess

import pytest

from builder import build_cli
from scripts import reviewer_bot


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
