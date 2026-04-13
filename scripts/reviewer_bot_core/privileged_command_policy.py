"""Privileged command validation and planning policy."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum

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


class PrivilegedCommandId(StrEnum):
    ACCEPT_NO_FLS_CHANGES = "accept-no-fls-changes"


@dataclass(frozen=True)
class PendingAcceptNoFlsChangesRecord:
    source_event_key: str
    command_name: str
    issue_number: int
    actor: str
    authorization_required_permission: str
    authorization_authorized: bool
    target_kind: str
    target_number: int
    target_labels_snapshot: tuple[str, ...]
    status: str
    created_at: str
    completed_at: str | None = None
    result_code: str | None = None
    result_message: str | None = None
    opened_pr_url: str | None = None


@dataclass(frozen=True)
class PrivilegedExecutionContext:
    target_repo_root: str
    base_branch: str
    branch_probe_name: str
    branch_name: str
    expected_changed_files: tuple[str, ...]
    existing_open_pr_url: str | None = None


@dataclass(frozen=True)
class BlockedPrivilegedHandoff:
    reason: str
    response: str


@dataclass(frozen=True)
class AllowedPrivilegedHandoff:
    source_event_key: str
    command_name: str
    issue_number: int
    actor: str
    authorization_required_permission: str
    authorization_authorized: bool
    target_kind: str
    target_number: int
    target_labels_snapshot: tuple[str, ...]


@dataclass(frozen=True)
class BlockedPrivilegedExecution:
    status: str = "failed_closed"
    result_code: str = "authorization_failed"
    result_message: str | None = None
    opened_pr_url: None = None


@dataclass(frozen=True)
class CompletePrivilegedExecution:
    status: str
    result_code: str
    result_message: str | None
    opened_pr_url: str | None = None


@dataclass(frozen=True)
class ExecutePrivilegedPlan:
    record: PendingAcceptNoFlsChangesRecord
    execution_context: PrivilegedExecutionContext


def _blocked_privileged_execution(*, result_code: str, result_message: str | None = None) -> BlockedPrivilegedExecution:
    return BlockedPrivilegedExecution(result_code=result_code, result_message=result_message)


def _pending_accept_no_fls_changes_record_from_request(request) -> PendingAcceptNoFlsChangesRecord:
    labels = tuple(sorted(request.issue_labels))
    return PendingAcceptNoFlsChangesRecord(
        source_event_key="",
        command_name=PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value,
        issue_number=request.issue_number,
        actor=request.actor,
        authorization_required_permission="triage",
        authorization_authorized=True,
        target_kind="issue",
        target_number=request.issue_number,
        target_labels_snapshot=labels,
        status="pending",
        created_at="",
    )


def _accept_no_fls_changes_execution_context(*, target_repo_root: str) -> PrivilegedExecutionContext:
    return PrivilegedExecutionContext(
        target_repo_root=target_repo_root,
        base_branch="",
        branch_probe_name="",
        branch_name="",
        expected_changed_files=("src/spec.lock",),
    )


def _snapshot_issue_labels(issue_snapshot: dict) -> tuple[str, ...]:
    labels: list[str] = []
    for label in issue_snapshot.get("labels", []):
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str):
            labels.append(name)
    return tuple(sorted(labels))


def _sidecars(review_data: dict) -> dict:
    sidecars = review_data.get("sidecars")
    if not isinstance(sidecars, dict):
        sidecars = {}
        review_data["sidecars"] = sidecars
    return sidecars


def get_pending_privileged_commands(review_data: dict) -> dict:
    pending = _sidecars(review_data).get("pending_privileged_commands")
    if not isinstance(pending, dict):
        pending = {}
        _sidecars(review_data)["pending_privileged_commands"] = pending
    return pending


def put_pending_accept_no_fls_changes(review_data: dict, record: PendingAcceptNoFlsChangesRecord) -> None:
    get_pending_privileged_commands(review_data)[record.source_event_key] = deepcopy(asdict(record))


def load_pending_accept_no_fls_changes(review_data: dict, source_event_key: str) -> PendingAcceptNoFlsChangesRecord | None:
    record = get_pending_privileged_commands(review_data).get(source_event_key)
    return _coerce_pending_accept_no_fls_changes_record(record)


def _coerce_pending_accept_no_fls_changes_record(record: dict | None) -> PendingAcceptNoFlsChangesRecord | None:
    if not isinstance(record, dict):
        return None
    try:
        return PendingAcceptNoFlsChangesRecord(
            source_event_key=str(record["source_event_key"]),
            command_name=str(record["command_name"]),
            issue_number=int(record["issue_number"]),
            actor=str(record["actor"]),
            authorization_required_permission=str(record["authorization_required_permission"]),
            authorization_authorized=bool(record["authorization_authorized"]),
            target_kind=str(record["target_kind"]),
            target_number=int(record["target_number"]),
            target_labels_snapshot=tuple(record["target_labels_snapshot"]),
            status=str(record["status"]),
            created_at=str(record["created_at"]),
            completed_at=(str(record["completed_at"]) if record.get("completed_at") is not None else None),
            result_code=(str(record["result_code"]) if record.get("result_code") is not None else None),
            result_message=(str(record["result_message"]) if record.get("result_message") is not None else None),
            opened_pr_url=(str(record["opened_pr_url"]) if record.get("opened_pr_url") is not None else None),
        )
    except (KeyError, TypeError, ValueError):
        return None


def find_pending_accept_no_fls_changes(state: dict, source_event_key: str) -> tuple[int, dict, PendingAcceptNoFlsChangesRecord] | None:
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return None
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        record = _coerce_pending_accept_no_fls_changes_record(
            get_pending_privileged_commands(review_data).get(source_event_key)
        )
        if record is None:
            continue
        try:
            issue_number = int(issue_key)
        except (TypeError, ValueError):
            issue_number = record.issue_number
        return issue_number, review_data, record
    return None


def mark_pending_accept_no_fls_changes_executed(
    review_data: dict,
    source_event_key: str,
    *,
    completed_at: str,
    result: str,
    result_message: str,
    opened_pr_url: str | None = None,
) -> bool:
    record = get_pending_privileged_commands(review_data).get(source_event_key)
    if not isinstance(record, dict):
        return False
    record["status"] = "executed"
    record["completed_at"] = completed_at
    record["result_code"] = result
    record["result_message"] = result_message
    if opened_pr_url is not None:
        record["opened_pr_url"] = opened_pr_url
    return True


def mark_pending_accept_no_fls_changes_failed_closed(
    review_data: dict,
    source_event_key: str,
    *,
    completed_at: str,
    result: str,
    result_message: str | None = None,
) -> bool:
    record = get_pending_privileged_commands(review_data).get(source_event_key)
    if not isinstance(record, dict):
        return False
    record["status"] = "failed_closed"
    record["completed_at"] = completed_at
    record["result_code"] = result
    if result_message is not None:
        record["result_message"] = result_message
    return True


@dataclass(frozen=True)
class AcceptNoFlsChangesPlan:
    ordered_steps: list[str]
    revalidation_checkpoints: list[str]
    expected_changed_files: list[str]
    branch_probe_name: str
    branch_name: str
    base_branch: str
    add_paths: list[str]
    git_checkout_args: list[str]
    git_commit_args: list[str]
    git_push_args: list[str]
    commit_message: str
    pull_request_title: str
    pull_request_body: str

    def build_execution_context(self, *, target_repo_root: str, existing_open_pr_url: str | None = None) -> PrivilegedExecutionContext:
        return PrivilegedExecutionContext(
            target_repo_root=target_repo_root,
            base_branch=self.base_branch,
            branch_probe_name=self.branch_probe_name,
            branch_name=self.branch_name,
            expected_changed_files=tuple(self.expected_changed_files),
            existing_open_pr_url=existing_open_pr_url,
        )


def validate_accept_no_fls_changes_handoff(
    request,
    permission_status: str,
    *,
    source_event_key: str = "",
) -> BlockedPrivilegedHandoff | AllowedPrivilegedHandoff:
    if request.is_pull_request:
        return BlockedPrivilegedHandoff(
            reason="pull_request_target_not_allowed",
            response="❌ This command can only be used on issues, not PRs.",
        )
    labels = tuple(sorted(request.issue_labels))
    if "fls-audit" not in labels:
        return BlockedPrivilegedHandoff(
            reason="missing_fls_audit_label",
            response="❌ This command is only available on issues labeled `fls-audit`.",
        )
    if permission_status == "unavailable":
        return BlockedPrivilegedHandoff(
            reason="authorization_unavailable",
            response="❌ Unable to verify triage permissions right now; refusing to run this command.",
        )
    if permission_status != "granted":
        return BlockedPrivilegedHandoff(
            reason="authorization_failed",
            response="❌ You must have triage permissions to run this command.",
        )
    return AllowedPrivilegedHandoff(
        source_event_key=source_event_key,
        command_name=PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value,
        issue_number=request.issue_number,
        actor=request.comment_author,
        authorization_required_permission="triage",
        authorization_authorized=True,
        target_kind="issue",
        target_number=request.issue_number,
        target_labels_snapshot=labels,
    )


def build_pending_privileged_command(*, created_at: str, handoff: AllowedPrivilegedHandoff) -> PendingAcceptNoFlsChangesRecord:
    return PendingAcceptNoFlsChangesRecord(
        source_event_key=handoff.source_event_key,
        command_name=handoff.command_name,
        issue_number=handoff.issue_number,
        actor=handoff.actor,
        authorization_required_permission=handoff.authorization_required_permission,
        authorization_authorized=handoff.authorization_authorized,
        target_kind=handoff.target_kind,
        target_number=handoff.target_number,
        target_labels_snapshot=handoff.target_labels_snapshot,
        status="pending",
        created_at=created_at,
    )


def prevalidate_accept_no_fls_changes_request(
    request,
    permission_status: str,
    changed_files_before: list[str],
) -> BlockedPrivilegedExecution | ExecutePrivilegedPlan:
    if request.is_pull_request:
        return _blocked_privileged_execution(
            result_code="pull_request_target_not_allowed",
            result_message="❌ This command can only be used on issues, not PRs.",
        )
    labels = tuple(sorted(request.issue_labels))
    if "fls-audit" not in labels:
        return _blocked_privileged_execution(
            result_code="missing_fls_audit_label",
            result_message="❌ This command is only available on issues labeled `fls-audit`.",
        )
    if permission_status == "unavailable":
        return _blocked_privileged_execution(
            result_code="authorization_unavailable",
            result_message="❌ Unable to verify triage permissions right now; refusing to run this command.",
        )
    if permission_status != "granted":
        return _blocked_privileged_execution(
            result_code="authorization_failed",
            result_message="❌ You must have triage permissions to run this command.",
        )
    if changed_files_before:
        return _blocked_privileged_execution(
            result_code="working_tree_not_clean",
            result_message="❌ Working tree is not clean; refusing to update spec.lock.",
        )
    return ExecutePrivilegedPlan(
        record=_pending_accept_no_fls_changes_record_from_request(request),
        execution_context=_accept_no_fls_changes_execution_context(target_repo_root=""),
    )


def revalidate_pending_accept_no_fls_changes(
    record: PendingAcceptNoFlsChangesRecord,
    issue_snapshot: dict,
    permission_status: str,
    *,
    target_repo_root: str,
) -> BlockedPrivilegedExecution | ExecutePrivilegedPlan:
    if record.command_name != PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value:
        return _blocked_privileged_execution(result_code="unsupported_command")
    if not isinstance(issue_snapshot, dict):
        return _blocked_privileged_execution(result_code="unsupported_command")
    if isinstance(issue_snapshot.get("pull_request"), dict):
        return _blocked_privileged_execution(
            result_code="pull_request_target_not_allowed",
            result_message="❌ This command can only be used on issues, not PRs.",
        )
    labels = _snapshot_issue_labels(issue_snapshot)
    if "fls-audit" not in labels:
        return _blocked_privileged_execution(
            result_code="missing_fls_audit_label",
            result_message="❌ This command is only available on issues labeled `fls-audit`.",
        )
    if permission_status == "unavailable":
        return _blocked_privileged_execution(
            result_code="authorization_unavailable",
            result_message="❌ Unable to verify triage permissions right now; refusing to run this command.",
        )
    if permission_status != "granted":
        return _blocked_privileged_execution(
            result_code="authorization_failed",
            result_message="❌ You must have triage permissions to run this command.",
        )
    revalidated_record = PendingAcceptNoFlsChangesRecord(
        source_event_key=record.source_event_key,
        command_name=record.command_name,
        issue_number=record.issue_number,
        actor=record.actor,
        authorization_required_permission=record.authorization_required_permission,
        authorization_authorized=record.authorization_authorized,
        target_kind=record.target_kind,
        target_number=record.target_number,
        target_labels_snapshot=labels,
        status=record.status,
        created_at=record.created_at,
        completed_at=record.completed_at,
        result_code=record.result_code,
        result_message=record.result_message,
        opened_pr_url=record.opened_pr_url,
    )
    return ExecutePrivilegedPlan(
        record=revalidated_record,
        execution_context=_accept_no_fls_changes_execution_context(target_repo_root=target_repo_root),
    )


def derive_accept_no_fls_changes_branch_name(
    *,
    issue_number: int,
    branch_date: str,
    branch_suffix: str | None = None,
) -> str:
    branch_name = f"chore/spec-lock-{branch_date}-issue-{issue_number}"
    if branch_suffix:
        branch_name = f"{branch_name}-{branch_suffix}"
    return branch_name


def assess_accept_no_fls_changes_post_update(
    *,
    audit_returncode: int,
    audit_details: str,
    update_returncode: int,
    update_details: str,
    changed_files_after: list[str],
) -> BlockedPrivilegedExecution | CompletePrivilegedExecution | None:
    if audit_returncode == 2:
        return CompletePrivilegedExecution(
            status="failed_closed",
            result_code="audit_reported_guideline_impact",
            result_message=(
                "❌ The audit reports affected guidelines. Please review and open a PR with "
                "the necessary guideline updates instead."
            ),
        )
    if audit_returncode != 0:
        detail_text = f"\n\nDetails:\n```\n{audit_details}\n```" if audit_details else ""
        return CompletePrivilegedExecution(status="failed_closed", result_code="audit_failed", result_message=f"❌ Audit command failed.{detail_text}")
    if update_returncode != 0:
        detail_text = f"\n\nDetails:\n```\n{update_details}\n```" if update_details else ""
        return CompletePrivilegedExecution(status="failed_closed", result_code="update_failed", result_message=f"❌ Failed to update spec.lock.{detail_text}")
    if not changed_files_after:
        return CompletePrivilegedExecution(status="executed", result_code="already_up_to_date", result_message="✅ `src/spec.lock` is already up to date; no PR needed.")
    unexpected = sorted(path for path in changed_files_after if path != "src/spec.lock")
    if unexpected:
        return CompletePrivilegedExecution(
            status="failed_closed",
            result_code="unexpected_changed_files",
            result_message=(
                "❌ Unexpected tracked file changes detected; refusing to open a PR. "
                f"Please review: {', '.join(unexpected)}"
            ),
        )
    return None


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
) -> CompletePrivilegedExecution | AcceptNoFlsChangesPlan:
    assessment = assess_accept_no_fls_changes_post_update(
        audit_returncode=audit_returncode,
        audit_details=audit_details,
        update_returncode=update_returncode,
        update_details=update_details,
        changed_files_after=changed_files_after,
    )
    if assessment is not None:
        return assessment
    branch_probe_name = derive_accept_no_fls_changes_branch_name(
        issue_number=issue_number,
        branch_date=branch_date,
    )
    effective_suffix = branch_suffix if branch_exists else None
    branch_name = derive_accept_no_fls_changes_branch_name(
        issue_number=issue_number,
        branch_date=branch_date,
        branch_suffix=effective_suffix,
    )
    plan = AcceptNoFlsChangesPlan(
        ordered_steps=list(ORDERED_EXECUTION_STEPS),
        revalidation_checkpoints=list(REVALIDATION_CHECKPOINTS),
        expected_changed_files=["src/spec.lock"],
        branch_probe_name=branch_probe_name,
        branch_name=branch_name,
        base_branch=base_branch,
        add_paths=["src/spec.lock"],
        git_checkout_args=["git", "checkout", "-b", branch_name],
        git_commit_args=[
            "git",
            "-c",
            "user.name=guidelines-bot",
            "-c",
            "user.email=guidelines-bot@users.noreply.github.com",
            "commit",
            "-m",
            COMMIT_MESSAGE,
        ],
        git_push_args=["git", "push", "origin", branch_name],
        commit_message=COMMIT_MESSAGE,
        pull_request_title=PR_TITLE,
        pull_request_body=(
            "Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\n"
            f"Closes #{issue_number}"
        ),
    )
    return plan
