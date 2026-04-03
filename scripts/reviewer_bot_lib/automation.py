"""Automation-heavy reviewer-bot helpers."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .context import PrivilegedCommandRequest
from .event_inputs import (
    build_privileged_command_request as decode_privileged_command_request,
)
from .event_inputs import (
    get_target_repo_root as decode_target_repo_root,
    parse_issue_labels as decode_issue_labels,
)


def run_command(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Command failed").strip())
    return result


def summarize_output(result: subprocess.CompletedProcess, limit: int = 20) -> str:
    combined = "\n".join([line for line in [result.stdout, result.stderr] if line]).strip()
    if not combined:
        return ""
    lines = combined.splitlines()
    return "\n".join(lines[-limit:])


def list_changed_files(repo_root: Path) -> list[str]:
    files: list[str] = []
    for command in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        result = run_command(command, cwd=repo_root)
        for line in result.stdout.splitlines():
            path = line.strip()
            if path:
                files.append(path)
    return sorted(set(files))


def get_target_repo_root(bot) -> Path:
    configured = decode_target_repo_root(bot)
    if configured is not None:
        return configured
    return Path(__file__).resolve().parents[2]


def build_privileged_command_request(bot, *, issue_number: int, actor: str = "", command_name: str = "") -> PrivilegedCommandRequest:
    return decode_privileged_command_request(
        bot,
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
    )


def bot_parse_issue_labels(bot) -> list[str]:
    return decode_issue_labels(bot)


def get_default_branch(bot) -> str:
    repo_info = bot.github_api("GET", "")
    if isinstance(repo_info, dict):
        return repo_info.get("default_branch", "main")
    return "main"


def find_open_pr_for_branch_status(bot, branch: str) -> tuple[str, dict | None]:
    owner = bot.get_config_value("REPO_OWNER", "").strip()
    branch = branch.strip()
    if not owner or not branch:
        return "not_found", None
    response = bot.github_api_request(
        "GET",
        f"pulls?state=open&head={owner}:{branch}",
        retry_policy="idempotent_read",
    )
    if not response.ok:
        return "unavailable", None
    payload = response.payload
    if not isinstance(payload, list):
        return "unavailable", None
    if payload:
        first = payload[0]
        if isinstance(first, dict):
            return "found", first
    return "not_found", None


def find_open_pr_for_branch(bot, branch: str) -> dict | None:
    status, pr = find_open_pr_for_branch_status(bot, branch)
    if status != "found":
        return None
    return pr


def create_pull_request(bot, branch: str, base: str, issue_number: int) -> dict | None:
    lookup_status, existing = bot.find_open_pr_for_branch_status(branch)
    if lookup_status == "found":
        return existing
    if lookup_status == "unavailable":
        raise RuntimeError(f"Unable to determine whether branch '{branch}' already has an open PR")
    title = "chore: update spec.lock (no guideline impact)"
    body = (
        "Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\n"
        f"Closes #{issue_number}"
    )
    response = bot.github_api(
        "POST",
        "pulls",
        {"title": title, "head": branch, "base": base, "body": body},
    )
    if isinstance(response, dict):
        return response
    return None


def handle_accept_no_fls_changes_command(
    bot,
    issue_number: int,
    comment_author: str,
    request: PrivilegedCommandRequest | None = None,
) -> tuple[str, bool]:
    privileged_request = request or build_privileged_command_request(
        bot,
        issue_number=issue_number,
        actor=comment_author,
        command_name="accept-no-fls-changes",
    )
    if privileged_request.is_pull_request:
        return "❌ This command can only be used on issues, not PRs.", False
    labels = list(privileged_request.issue_labels)
    if bot.FLS_AUDIT_LABEL not in labels:
        return "❌ This command is only available on issues labeled `fls-audit`.", False
    permission_status = bot.get_user_permission_status(comment_author, "triage")
    if permission_status == "unavailable":
        return "❌ Unable to verify triage permissions right now; refusing to run this command.", False
    if permission_status != "granted":
        return "❌ You must have triage permissions to run this command.", False

    repo_root = Path(privileged_request.target_repo_root) if privileged_request.target_repo_root else get_target_repo_root(bot)
    if bot.list_changed_files(repo_root):
        return "❌ Working tree is not clean; refusing to update spec.lock.", False

    audit_result = bot.run_command(
        ["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        cwd=repo_root,
        check=False,
    )
    if audit_result.returncode == 2:
        return (
            "❌ The audit reports affected guidelines. Please review and open a PR with "
            "the necessary guideline updates instead.",
            False,
        )
    if audit_result.returncode != 0:
        details = bot.summarize_output(audit_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return f"❌ Audit command failed.{detail_text}", False

    update_result = bot.run_command(
        ["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"],
        cwd=repo_root,
        check=False,
    )
    if update_result.returncode != 0:
        details = bot.summarize_output(update_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return f"❌ Failed to update spec.lock.{detail_text}", False

    changed_files = bot.list_changed_files(repo_root)
    if not changed_files:
        return "✅ `src/spec.lock` is already up to date; no PR needed.", True

    unexpected = {path for path in changed_files if path != "src/spec.lock"}
    if unexpected:
        paths = ", ".join(sorted(unexpected))
        return (
            "❌ Unexpected tracked file changes detected; refusing to open a PR. "
            f"Please review: {paths}",
            False,
        )

    branch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_branch = bot.get_default_branch()
    branch_name = f"chore/spec-lock-{branch_date}-issue-{issue_number}"
    if bot.run_command(["git", "rev-parse", "--verify", branch_name], cwd=repo_root, check=False).returncode == 0:
        suffix = datetime.now(timezone.utc).strftime("%H%M%S")
        branch_name = f"{branch_name}-{suffix}"

    try:
        bot.run_command(["git", "checkout", "-b", branch_name], cwd=repo_root)
        bot.run_command(["git", "add", "src/spec.lock"], cwd=repo_root)
        bot.run_command(
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
            cwd=repo_root,
        )
        bot.run_command(["git", "push", "origin", branch_name], cwd=repo_root)
    except RuntimeError as exc:
        return f"❌ Failed to create branch or push changes: {exc}", False

    pr = bot.create_pull_request(branch_name, base_branch, issue_number)
    if not pr or "html_url" not in pr:
        return "❌ Failed to open a pull request for the spec.lock update.", False

    return f"✅ Opened PR {pr['html_url']}", True
