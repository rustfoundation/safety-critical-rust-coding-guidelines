import pytest

pytestmark = pytest.mark.integration

from builder import build_cli
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
    harness.set_privileged_context(
        labels=[FLS_AUDIT_LABEL],
        is_pull_request=False,
        target_repo_root=tmp_path,
    )
    harness.stub_permission("granted")
    observed = {"cwd": None}

    def fake_list_changed_files(repo_root):
        observed["cwd"] = repo_root
        return ["README.md"]

    harness.runtime.list_changed_files = fake_list_changed_files

    message, success = harness.handle_accept_no_fls_changes(42, "alice")

    assert (message, success) == ("❌ Working tree is not clean; refusing to update spec.lock.", False)
    assert observed["cwd"] == tmp_path

def test_accept_no_fls_changes_uses_locked_nested_uv_commands(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    harness.set_privileged_context(
        labels=[FLS_AUDIT_LABEL],
        is_pull_request=False,
        target_repo_root=tmp_path,
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

    message, success = harness.handle_accept_no_fls_changes(42, "alice")

    assert (message, success) == ("✅ `src/spec.lock` is already up to date; no PR needed.", True)
    assert list_calls["count"] == 2
    assert runner.calls == [
        (["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"], tmp_path, False),
        (["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"], tmp_path, False),
    ]

def test_accept_no_fls_changes_surfaces_locked_uv_failure_details(monkeypatch, tmp_path):
    harness = CommandHarness(monkeypatch)
    harness.set_privileged_context(
        labels=[FLS_AUDIT_LABEL],
        is_pull_request=False,
        target_repo_root=tmp_path,
    )
    harness.stub_permission("granted")
    harness.runtime.list_changed_files = lambda repo_root: []
    runner = harness.automation_runner()
    runner.when(
        ["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        returncode=1,
        stderr="error: lockfile at uv.lock needs to be updated, but --locked was provided",
    )

    message, success = harness.handle_accept_no_fls_changes(42, "alice")

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
