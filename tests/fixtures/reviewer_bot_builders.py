from scripts.reviewer_bot_lib import review_state
from scripts.reviewer_bot_lib.context import (
    AssignmentRequest,
    CommentEventRequest,
    PrCommentTrustContext,
    PrivilegedCommandRequest,
)


def build_assignment_request(
    *,
    issue_number: int,
    issue_author: str = "",
    is_pull_request: bool = False,
    issue_labels: tuple[str, ...] = (),
    repo_owner: str = "",
    repo_name: str = "",
) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=issue_number,
        issue_author=issue_author,
        is_pull_request=is_pull_request,
        issue_labels=issue_labels,
        repo_owner=repo_owner,
        repo_name=repo_name,
    )


def build_privileged_command_request(
    *,
    issue_number: int,
    actor: str = "",
    command_name: str = "",
    is_pull_request: bool = False,
    issue_labels: tuple[str, ...] = (),
    target_repo_root: str = "",
    workflow_run_reconcile_pr_number: int | None = None,
    workflow_run_reconcile_head_sha: str = "",
    workflow_run_head_sha: str = "",
) -> PrivilegedCommandRequest:
    return PrivilegedCommandRequest(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
        is_pull_request=is_pull_request,
        issue_labels=issue_labels,
        target_repo_root=target_repo_root,
        workflow_run_reconcile_pr_number=workflow_run_reconcile_pr_number,
        workflow_run_reconcile_head_sha=workflow_run_reconcile_head_sha,
        workflow_run_head_sha=workflow_run_head_sha,
    )


def build_comment_event_request(
    *,
    issue_number: int,
    is_pull_request: bool,
    issue_state: str = "",
    issue_author: str = "",
    comment_id: int = 0,
    comment_author: str = "",
    comment_author_id: int = 0,
    comment_body: str = "",
    comment_created_at: str = "",
    comment_source_event_key: str = "",
    comment_user_type: str = "",
    comment_sender_type: str = "",
    comment_installation_id: str = "",
    comment_performed_via_github_app: bool = False,
) -> CommentEventRequest:
    return CommentEventRequest(
        issue_number=issue_number,
        is_pull_request=is_pull_request,
        issue_state=issue_state,
        issue_author=issue_author,
        comment_id=comment_id,
        comment_author=comment_author,
        comment_author_id=comment_author_id,
        comment_body=comment_body,
        comment_created_at=comment_created_at,
        comment_source_event_key=comment_source_event_key,
        comment_user_type=comment_user_type,
        comment_sender_type=comment_sender_type,
        comment_installation_id=comment_installation_id,
        comment_performed_via_github_app=comment_performed_via_github_app,
    )


def build_pr_comment_trust_context(
    *,
    github_repository: str = "",
    comment_author_association: str = "",
    current_workflow_file: str = "",
    github_ref: str = "",
    github_run_id: int = 0,
    github_run_attempt: int = 0,
) -> PrCommentTrustContext:
    return PrCommentTrustContext(
        github_repository=github_repository,
        comment_author_association=comment_author_association,
        current_workflow_file=current_workflow_file,
        github_ref=github_ref,
        github_run_id=github_run_id,
        github_run_attempt=github_run_attempt,
    )


def make_tracked_review_state(
    state: dict,
    issue_number: int,
    *,
    reviewer: str | None = None,
    assigned_at: str | None = None,
    active_cycle_started_at: str | None = None,
    repair_needed: dict | None = None,
):
    review = review_state.ensure_review_entry(state, issue_number, create=True)
    if review is None:
        raise AssertionError(f"Unable to create review entry for #{issue_number}")
    if reviewer is not None:
        review["current_reviewer"] = reviewer
    if assigned_at is not None:
        review["assigned_at"] = assigned_at
    if active_cycle_started_at is not None:
        review["active_cycle_started_at"] = active_cycle_started_at
    if repair_needed is not None:
        review["repair_needed"] = repair_needed
    return review


def issue_snapshot(
    issue_number: int,
    *,
    state: str = "open",
    is_pull_request: bool = False,
    labels: list[dict] | list[str] | None = None,
) -> dict:
    return {
        "number": issue_number,
        "state": state,
        "pull_request": {} if is_pull_request else None,
        "labels": labels or [],
    }


def pull_request_payload(
    issue_number: int,
    *,
    head_sha: str,
    author: str = "alice",
    head_repo_full_name: str | None = None,
) -> dict:
    payload = {
        "number": issue_number,
        "state": "open",
        "head": {"sha": head_sha},
        "user": {"login": author},
    }
    if head_repo_full_name is not None:
        payload["head"]["repo"] = {"full_name": head_repo_full_name}
    return payload


def review_payload(
    review_id: int,
    *,
    state: str,
    submitted_at: str,
    commit_id: str,
    author: str,
) -> dict:
    return {
        "id": review_id,
        "state": state,
        "submitted_at": submitted_at,
        "commit_id": commit_id,
        "user": {"login": author},
    }


def accept_reviewer_comment(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
) -> bool:
    return review_state.accept_channel_event(
        review_data,
        "reviewer_comment",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
    )


def accept_reviewer_review(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    reviewed_head_sha: str,
    source_precedence: int = 1,
) -> bool:
    return review_state.accept_channel_event(
        review_data,
        "reviewer_review",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
        reviewed_head_sha=reviewed_head_sha,
        source_precedence=source_precedence,
    )


def accept_contributor_comment(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
) -> bool:
    return review_state.accept_channel_event(
        review_data,
        "contributor_comment",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
    )


def accept_contributor_revision(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    head_sha: str,
) -> bool:
    return review_state.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
        reviewed_head_sha=head_sha,
    )


def accepted_record(
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    reviewed_head_sha: str | None = None,
    head_sha: str | None = None,
) -> dict:
    record = {
        "semantic_key": semantic_key,
        "timestamp": timestamp,
        "actor": actor,
    }
    if reviewed_head_sha is not None:
        record["reviewed_head_sha"] = reviewed_head_sha
    if head_sha is not None:
        record["head_sha"] = head_sha
    return record
