"""Automation-heavy reviewer-bot helpers."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.reviewer_bot_core import privileged_command_policy

from .context import PrivilegedCommandRequest

EXECUTOR_PHASE_CHECKLIST = [
    "audit_command_execution",
    "spec_lock_update_command_execution",
    "changed_file_validation_execution",
    "branch_existence_check",
    "branch_creation",
    "git_add",
    "git_commit",
    "git_push",
    "pull_request_create",
    "execute_time_revalidation_checkpoints",
]


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
    configured = bot.get_config_value("REVIEWER_BOT_TARGET_REPO_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2]
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


def create_pull_request(bot, branch: str, base: str, issue_number: int, *, title: str | None = None, body: str | None = None) -> dict | None:
    lookup_status, existing = find_open_pr_for_branch_status(bot, branch)
    if lookup_status == "found":
        return existing
    if lookup_status == "unavailable":
        raise RuntimeError(f"Unable to determine whether branch '{branch}' already has an open PR")
    if title is None or body is None:
        raise RuntimeError("PR title/body must be provided by privileged command planning")
    response = bot.github_api(
        "POST",
        "pulls",
        {"title": title, "head": branch, "base": base, "body": body},
    )
    if isinstance(response, dict):
        return response
    return None


def _execute_accept_no_fls_changes_plan(
    bot,
    repo_root: Path,
    issue_number: int,
    plan: privileged_command_policy.AcceptNoFlsChangesPlan,
) -> privileged_command_policy.CompletePrivilegedExecution:
    try:
        bot.adapters.automation.run_command(plan.git_checkout_args, cwd=repo_root)
        bot.adapters.automation.run_command(["git", "add", *plan.add_paths], cwd=repo_root)
        bot.adapters.automation.run_command(plan.git_commit_args, cwd=repo_root)
        bot.adapters.automation.run_command(plan.git_push_args, cwd=repo_root)
    except RuntimeError as exc:
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="branch_or_push_failed",
            result_message=f"❌ Failed to create branch or push changes: {exc}",
        )

    pr = create_pull_request(
        bot,
        plan.branch_name,
        plan.base_branch,
        issue_number,
        title=plan.pull_request_title,
        body=plan.pull_request_body,
    )
    if not pr or "html_url" not in pr:
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="pull_request_creation_failed",
            result_message="❌ Failed to open a pull request for the spec.lock update.",
        )

    return privileged_command_policy.CompletePrivilegedExecution(
        status="executed",
        result_code="opened_pull_request",
        result_message=f"✅ Opened PR {pr['html_url']}",
        opened_pr_url=pr["html_url"],
    )


def _resolve_accept_no_fls_changes_plan(
    bot,
    repo_root: Path,
    issue_number: int,
    *,
    audit_result: subprocess.CompletedProcess,
    update_result: subprocess.CompletedProcess,
    changed_files_after: list[str],
 ) -> privileged_command_policy.CompletePrivilegedExecution | privileged_command_policy.AcceptNoFlsChangesPlan:
    post_update = privileged_command_policy.assess_accept_no_fls_changes_post_update(
        audit_returncode=audit_result.returncode,
        audit_details=bot.adapters.automation.summarize_output(audit_result),
        update_returncode=update_result.returncode,
        update_details=bot.adapters.automation.summarize_output(update_result),
        changed_files_after=changed_files_after,
    )
    if post_update is not None:
        return post_update
    base_branch = bot.adapters.automation.get_default_branch()
    branch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    provisional = privileged_command_policy.plan_accept_no_fls_changes_execution(
        issue_number=issue_number,
        audit_returncode=0,
        audit_details="",
        update_returncode=0,
        update_details="",
        changed_files_after=changed_files_after,
        branch_date=branch_date,
        base_branch=base_branch,
        branch_exists=False,
        branch_suffix=None,
    )
    if not isinstance(provisional, privileged_command_policy.AcceptNoFlsChangesPlan):
        return provisional
    branch_exists = bot.adapters.automation.run_command(
        ["git", "rev-parse", "--verify", provisional.branch_probe_name],
        cwd=repo_root,
        check=False,
    ).returncode == 0
    branch_suffix = datetime.now(timezone.utc).strftime("%H%M%S") if branch_exists else None
    return privileged_command_policy.plan_accept_no_fls_changes_execution(
        issue_number=issue_number,
        audit_returncode=0,
        audit_details="",
        update_returncode=0,
        update_details="",
        changed_files_after=changed_files_after,
        branch_date=branch_date,
        base_branch=base_branch,
        branch_exists=branch_exists,
        branch_suffix=branch_suffix,
    )


def handle_accept_no_fls_changes_command(
    bot,
    issue_number: int,
    comment_author: str,
    request: PrivilegedCommandRequest | None = None,
    execution_plan: privileged_command_policy.ExecutePrivilegedPlan | None = None,
) -> privileged_command_policy.CompletePrivilegedExecution:
    if execution_plan is None:
        if request is None:
            raise RuntimeError("handle_accept_no_fls_changes_command requires a canonical privileged request")
        permission_status = bot.github.get_user_permission_status(comment_author, "triage")
        repo_root = get_target_repo_root(bot)
        preflight = privileged_command_policy.prevalidate_accept_no_fls_changes_request(
            request,
            permission_status,
            bot.adapters.automation.list_changed_files(repo_root),
        )
        if isinstance(preflight, privileged_command_policy.BlockedPrivilegedExecution):
            return privileged_command_policy.CompletePrivilegedExecution(
                status="failed_closed",
                result_code=preflight.result_code,
                result_message=preflight.result_message,
            )
        execution_plan = privileged_command_policy.ExecutePrivilegedPlan(
            record=preflight.record,
            execution_context=privileged_command_policy.PrivilegedExecutionContext(
                target_repo_root=str(repo_root),
                base_branch=preflight.execution_context.base_branch,
                branch_probe_name=preflight.execution_context.branch_probe_name,
                branch_name=preflight.execution_context.branch_name,
                expected_changed_files=preflight.execution_context.expected_changed_files,
                existing_open_pr_url=preflight.execution_context.existing_open_pr_url,
            ),
        )
    if execution_plan.record.command_name != privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value:
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="unsupported_command",
        )
    repo_root = Path(execution_plan.execution_context.target_repo_root)

    audit_result = bot.adapters.automation.run_command(
        ["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        cwd=repo_root,
        check=False,
    )
    if audit_result.returncode == 2:
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="audit_reported_guideline_impact",
            result_message=(
                "❌ The audit reports affected guidelines. Please review and open a PR with "
                "the necessary guideline updates instead."
            ),
        )
    if audit_result.returncode != 0:
        details = bot.adapters.automation.summarize_output(audit_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="audit_failed",
            result_message=f"❌ Audit command failed.{detail_text}",
        )

    update_result = bot.adapters.automation.run_command(
        ["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"],
        cwd=repo_root,
        check=False,
    )
    if update_result.returncode != 0:
        details = bot.adapters.automation.summarize_output(update_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return privileged_command_policy.CompletePrivilegedExecution(
            status="failed_closed",
            result_code="update_failed",
            result_message=f"❌ Failed to update spec.lock.{detail_text}",
        )

    changed_files_after = bot.adapters.automation.list_changed_files(repo_root)
    planning = _resolve_accept_no_fls_changes_plan(
        bot,
        repo_root,
        execution_plan.record.issue_number,
        audit_result=audit_result,
        update_result=update_result,
        changed_files_after=changed_files_after,
    )
    if not isinstance(planning, privileged_command_policy.AcceptNoFlsChangesPlan):
        return planning
    return _execute_accept_no_fls_changes_plan(bot, repo_root, execution_plan.record.issue_number, planning)
