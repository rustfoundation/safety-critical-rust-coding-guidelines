"""Privileged command validation and planning policy."""

from __future__ import annotations

from dataclasses import dataclass

ORDERED_EXECUTION_STEPS = [
    "working_tree_clean_check",
    "audit_no_impact_check",
    "spec_lock_update",
    "changed_files_validation",
    "branch_name_derivation",
    "branch_existence_check",
    "branch_creation",
    "git_add_spec_lock",
    "git_commit",
    "git_push",
    "pull_request_create",
]

REVALIDATION_CHECKPOINTS = [
    "issue_not_pull_request",
    "fls_audit_label_present",
    "triage_permission_granted",
    "working_tree_clean_before_update",
    "audit_no_impact_before_update",
    "changed_files_exact_after_update",
]

COMMIT_MESSAGE = "chore: update spec.lock; no affected guidelines"
PR_TITLE = "chore: update spec.lock (no guideline impact)"


@dataclass(frozen=True)
class PendingPrivilegedCommandRecord:
    data: dict


@dataclass(frozen=True)
class AcceptNoFlsChangesPlan:
    ordered_steps: list[str]
    revalidation_checkpoints: list[str]
    branch_name: str
    base_branch: str
    add_paths: list[str]
    commit_message: str
    pull_request_title: str
    pull_request_body: str


@dataclass(frozen=True)
class PrivilegedDecision:
    kind: str
    message: str | None = None
    success: bool = False
    metadata: dict | None = None
    plan: AcceptNoFlsChangesPlan | None = None


def validate_accept_no_fls_changes_handoff(request, labels: list[str], permission_status: str) -> PrivilegedDecision:
    if request.is_pull_request:
        return PrivilegedDecision(kind="blocked", metadata={"reason": "pull_request_target_not_allowed"})
    if "fls-audit" not in labels:
        return PrivilegedDecision(kind="blocked", metadata={"reason": "missing_fls_audit_label"})
    if permission_status == "unavailable":
        return PrivilegedDecision(kind="blocked", metadata={"reason": "authorization_unavailable"})
    if permission_status != "granted":
        return PrivilegedDecision(kind="blocked", metadata={"reason": "authorization_failed"})
    return PrivilegedDecision(
        kind="handoff_allowed",
        metadata={
            "command_name": "accept-no-fls-changes",
            "issue_number": request.issue_number,
            "actor": request.comment_author,
            "authorization": {"required_permission": "triage", "authorized": True},
            "target": {"kind": "issue", "number": request.issue_number, "labels": sorted(labels)},
        },
    )


def build_pending_privileged_command(
    *,
    source_event_key: str,
    command_name: str,
    issue_number: int,
    actor: str,
    args: list[str],
    created_at: str,
    metadata: dict,
) -> PendingPrivilegedCommandRecord:
    return PendingPrivilegedCommandRecord(
        data={
            "source_event_key": source_event_key,
            "command_name": command_name,
            "issue_number": issue_number,
            "actor": actor,
            "args": args,
            "status": "pending",
            "created_at": created_at,
            "authorization": metadata["authorization"],
            "target": metadata["target"],
        }
    )


def prevalidate_accept_no_fls_changes_request(request, permission_status: str, changed_files_before: list[str]) -> PrivilegedDecision:
    if request.is_pull_request:
        return PrivilegedDecision(kind="blocked", message="❌ This command can only be used on issues, not PRs.", success=False)
    labels = list(request.issue_labels)
    if "fls-audit" not in labels:
        return PrivilegedDecision(kind="blocked", message="❌ This command is only available on issues labeled `fls-audit`.", success=False)
    if permission_status == "unavailable":
        return PrivilegedDecision(kind="blocked", message="❌ Unable to verify triage permissions right now; refusing to run this command.", success=False)
    if permission_status != "granted":
        return PrivilegedDecision(kind="blocked", message="❌ You must have triage permissions to run this command.", success=False)
    if changed_files_before:
        return PrivilegedDecision(kind="blocked", message="❌ Working tree is not clean; refusing to update spec.lock.", success=False)
    return PrivilegedDecision(kind="continue")


def plan_accept_no_fls_changes_execution(
    *,
    issue_number: int,
    audit_returncode: int,
    audit_details: str,
    update_returncode: int,
    update_details: str,
    changed_files_after: list[str],
    branch_date: str,
    base_branch: str,
    branch_exists: bool,
    branch_suffix: str | None = None,
) -> PrivilegedDecision:
    if audit_returncode == 2:
        return PrivilegedDecision(
            kind="blocked",
            message=(
                "❌ The audit reports affected guidelines. Please review and open a PR with "
                "the necessary guideline updates instead."
            ),
            success=False,
        )
    if audit_returncode != 0:
        detail_text = f"\n\nDetails:\n```\n{audit_details}\n```" if audit_details else ""
        return PrivilegedDecision(kind="blocked", message=f"❌ Audit command failed.{detail_text}", success=False)
    if update_returncode != 0:
        detail_text = f"\n\nDetails:\n```\n{update_details}\n```" if update_details else ""
        return PrivilegedDecision(kind="blocked", message=f"❌ Failed to update spec.lock.{detail_text}", success=False)
    if not changed_files_after:
        return PrivilegedDecision(kind="complete", message="✅ `src/spec.lock` is already up to date; no PR needed.", success=True)
    unexpected = sorted(path for path in changed_files_after if path != "src/spec.lock")
    if unexpected:
        return PrivilegedDecision(
            kind="blocked",
            message=(
                "❌ Unexpected tracked file changes detected; refusing to open a PR. "
                f"Please review: {', '.join(unexpected)}"
            ),
            success=False,
        )
    branch_name = f"chore/spec-lock-{branch_date}-issue-{issue_number}"
    if branch_exists and branch_suffix:
        branch_name = f"{branch_name}-{branch_suffix}"
    plan = AcceptNoFlsChangesPlan(
        ordered_steps=list(ORDERED_EXECUTION_STEPS),
        revalidation_checkpoints=list(REVALIDATION_CHECKPOINTS),
        branch_name=branch_name,
        base_branch=base_branch,
        add_paths=["src/spec.lock"],
        commit_message=COMMIT_MESSAGE,
        pull_request_title=PR_TITLE,
        pull_request_body=(
            "Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\n"
            f"Closes #{issue_number}"
        ),
    )
    return PrivilegedDecision(kind="execute_plan", success=True, plan=plan)
