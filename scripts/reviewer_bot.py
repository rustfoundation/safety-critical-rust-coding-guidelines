#!/usr/bin/env python3
"""
Reviewer Bot for Safety-Critical Rust Coding Guidelines

This bot manages round-robin assignment of reviewers for coding guideline and
FLS audit issues and PRs. It supports commands for passing reviews, vacations,
and label management.

All commands must be prefixed with @guidelines-bot /<command>:

  @guidelines-bot /pass [reason]
    - Skip the assigned reviewer for this issue/PR and assign the next person
    - The skipped reviewer stays in queue position for future assignments

  @guidelines-bot /away YYYY-MM-DD [reason]
    - Remove yourself from the queue until the specified date
    - Automatically assigns the next available reviewer

  @guidelines-bot /claim
    - Assign yourself as the reviewer for this issue/PR
    - Removes any existing reviewer assignment

  @guidelines-bot /release [@username] [reason]
    - Release your assignment from this issue/PR (or someone else's with triage+ permission)
    - Does NOT auto-assign the next reviewer (use /pass for that)

  @guidelines-bot /rectify
    - Reconcile this issue/PR's review state from GitHub review history
    - Useful when cross-repo review events cannot persist state immediately

  @guidelines-bot /r? @username
    - Assign a specific reviewer

  @guidelines-bot /r? producers
    - Assign the next reviewer from the round-robin queue
    - Useful for requesting a reviewer on an already-open issue/PR

  @guidelines-bot /label +label-name
    - Add a label to the issue/PR

  @guidelines-bot /label -label-name
    - Remove a label from the issue/PR

  @guidelines-bot /accept-no-fls-changes
    - Update spec.lock and open a PR when the audit reports no guideline impact

  @guidelines-bot /sync-members
    - Manually trigger sync of the queue with members.md

  @guidelines-bot /queue
    - Show current queue status and who's next up

  @guidelines-bot /commands
    - Show all available commands
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# GitHub API interaction
import yaml

try:
    import scripts.reviewer_bot_lib.commands as commands_module
    import scripts.reviewer_bot_lib.github_api as github_api_module
    import scripts.reviewer_bot_lib.lease_lock as lease_lock_module
    import scripts.reviewer_bot_lib.reviews as reviews_module
    import scripts.reviewer_bot_lib.state_store as state_store_module
    from scripts.reviewer_bot_lib import app as app_module
    from scripts.reviewer_bot_lib.config import (  # noqa: F401
        BOT_MENTION,
        COMMANDS,
        EVENT_INTENT_MUTATING,
        EVENT_INTENT_NON_MUTATING_DEFER,
        EVENT_INTENT_NON_MUTATING_READONLY,
        FLS_AUDIT_LABEL,
        LOCK_API_RETRY_LIMIT,
        LOCK_BLOCK_END_MARKER,
        LOCK_BLOCK_START_MARKER,
        LOCK_COMMIT_MARKER,
        LOCK_LEASE_TTL_SECONDS,
        LOCK_MAX_WAIT_SECONDS,
        LOCK_METADATA_KEYS,
        LOCK_REF_BOOTSTRAP_BRANCH,
        LOCK_REF_NAME,
        LOCK_RENEWAL_WINDOW_SECONDS,
        LOCK_RETRY_BASE_SECONDS,
        LOCK_SCHEMA_VERSION,
        MANDATORY_TRIAGE_APPROVER_LABEL,
        MANDATORY_TRIAGE_ESCALATION_TEMPLATE,
        MANDATORY_TRIAGE_SATISFIED_TEMPLATE,
        MAX_RECENT_ASSIGNMENTS,
        REVIEW_DEADLINE_DAYS,
        REVIEW_LABELS,
        REVIEWER_REQUEST_422_TEMPLATE,
        STATE_BLOCK_END_MARKER,
        STATE_BLOCK_START_MARKER,
        STATE_ISSUE_NUMBER,
        STATE_READ_RETRY_BASE_SECONDS,
        STATE_READ_RETRY_LIMIT,
        STATUS_AWAITING_REVIEW_COMPLETION_LABEL,
        STATUS_AWAITING_WRITE_APPROVAL_LABEL,
        STATUS_LABEL_CONFIG,
        STATUS_LABELS,
        TRANSITION_PERIOD_DAYS,
        AssignmentAttempt,
        GitHubApiResult,
        LeaseContext,
        StateIssueBodyParts,
        StateIssueSnapshot,
        get_commands_help,
    )
    from scripts.reviewer_bot_lib.guidance import (
        get_fls_audit_guidance,
        get_issue_guidance,
        get_pr_guidance,
    )
    from scripts.reviewer_bot_lib.members import fetch_members  # noqa: F401
    from scripts.reviewer_bot_lib.queue import (
        get_next_reviewer as queue_get_next_reviewer,
    )
    from scripts.reviewer_bot_lib.queue import (
        process_pass_until_expirations as queue_process_pass_until_expirations,
    )
    from scripts.reviewer_bot_lib.queue import (
        record_assignment as queue_record_assignment,
    )
    from scripts.reviewer_bot_lib.queue import (
        reposition_member_as_next as queue_reposition_member_as_next,
    )
    from scripts.reviewer_bot_lib.queue import (
        sync_members_with_queue as queue_sync_members_with_queue,
    )
except ImportError:
    import reviewer_bot_lib.app as app_module
    import reviewer_bot_lib.commands as commands_module
    import reviewer_bot_lib.github_api as github_api_module
    import reviewer_bot_lib.lease_lock as lease_lock_module
    import reviewer_bot_lib.reviews as reviews_module
    import reviewer_bot_lib.state_store as state_store_module
    from reviewer_bot_lib.config import (  # noqa: F401
        BOT_MENTION,
        COMMANDS,
        EVENT_INTENT_MUTATING,
        EVENT_INTENT_NON_MUTATING_DEFER,
        EVENT_INTENT_NON_MUTATING_READONLY,
        FLS_AUDIT_LABEL,
        LOCK_API_RETRY_LIMIT,
        LOCK_BLOCK_END_MARKER,
        LOCK_BLOCK_START_MARKER,
        LOCK_COMMIT_MARKER,
        LOCK_LEASE_TTL_SECONDS,
        LOCK_MAX_WAIT_SECONDS,
        LOCK_METADATA_KEYS,
        LOCK_REF_BOOTSTRAP_BRANCH,
        LOCK_REF_NAME,
        LOCK_RENEWAL_WINDOW_SECONDS,
        LOCK_RETRY_BASE_SECONDS,
        LOCK_SCHEMA_VERSION,
        MANDATORY_TRIAGE_APPROVER_LABEL,
        MANDATORY_TRIAGE_ESCALATION_TEMPLATE,
        MANDATORY_TRIAGE_SATISFIED_TEMPLATE,
        MAX_RECENT_ASSIGNMENTS,
        REVIEW_DEADLINE_DAYS,
        REVIEW_LABELS,
        REVIEWER_REQUEST_422_TEMPLATE,
        STATE_BLOCK_END_MARKER,
        STATE_BLOCK_START_MARKER,
        STATE_ISSUE_NUMBER,
        STATE_READ_RETRY_BASE_SECONDS,
        STATE_READ_RETRY_LIMIT,
        STATUS_AWAITING_REVIEW_COMPLETION_LABEL,
        STATUS_AWAITING_WRITE_APPROVAL_LABEL,
        STATUS_LABEL_CONFIG,
        STATUS_LABELS,
        TRANSITION_PERIOD_DAYS,
        AssignmentAttempt,
        GitHubApiResult,
        LeaseContext,
        StateIssueBodyParts,
        StateIssueSnapshot,
        get_commands_help,
    )
    from reviewer_bot_lib.guidance import (
        get_fls_audit_guidance,
        get_issue_guidance,
        get_pr_guidance,
    )
    from reviewer_bot_lib.members import fetch_members  # noqa: F401
    from reviewer_bot_lib.queue import (
        get_next_reviewer as queue_get_next_reviewer,
    )
    from reviewer_bot_lib.queue import (
        process_pass_until_expirations as queue_process_pass_until_expirations,
    )
    from reviewer_bot_lib.queue import (
        record_assignment as queue_record_assignment,
    )
    from reviewer_bot_lib.queue import (
        reposition_member_as_next as queue_reposition_member_as_next,
    )
    from reviewer_bot_lib.queue import (
        sync_members_with_queue as queue_sync_members_with_queue,
    )

requests = github_api_module.requests
random = lease_lock_module.random
time = lease_lock_module.time

# ==============================================================================
# GitHub API Helpers
# ==============================================================================


ACTIVE_LEASE_CONTEXT: LeaseContext | None = None
TOUCHED_ISSUE_NUMBERS: set[int] = set()


def get_github_token() -> str:
    return github_api_module.get_github_token()


def github_api_request(
    method: str,
    endpoint: str,
    data: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    *,
    suppress_error_log: bool = False,
) -> GitHubApiResult:
    return github_api_module.github_api_request(
        sys.modules[__name__],
        method,
        endpoint,
        data,
        extra_headers,
        suppress_error_log=suppress_error_log,
    )


def github_api(method: str, endpoint: str, data: dict | None = None) -> Any | None:
    return github_api_module.github_api(sys.modules[__name__], method, endpoint, data)


def post_comment(issue_number: int, body: str) -> bool:
    return github_api_module.post_comment(sys.modules[__name__], issue_number, body)


def get_repo_labels() -> set[str]:
    return github_api_module.get_repo_labels(sys.modules[__name__])


def add_label(issue_number: int, label: str) -> bool:
    return github_api_module.add_label(sys.modules[__name__], issue_number, label)


def remove_label(issue_number: int, label: str) -> bool:
    return github_api_module.remove_label(sys.modules[__name__], issue_number, label)


def add_label_with_status(issue_number: int, label: str) -> bool:
    return github_api_module.add_label_with_status(sys.modules[__name__], issue_number, label)


def remove_label_with_status(issue_number: int, label: str) -> bool:
    return github_api_module.remove_label_with_status(sys.modules[__name__], issue_number, label)


def ensure_label_exists(
    label: str,
    *,
    color: str | None = None,
    description: str | None = None,
) -> bool:
    return github_api_module.ensure_label_exists(
        sys.modules[__name__],
        label,
        color=color,
        description=description,
    )


def collect_touched_item(issue_number: int | None) -> None:
    """Record an issue/PR number for centralized status-label sync."""
    if isinstance(issue_number, int) and issue_number > 0:
        TOUCHED_ISSUE_NUMBERS.add(issue_number)


def drain_touched_items() -> list[int]:
    """Return touched issue numbers and clear the collector."""
    touched = sorted(TOUCHED_ISSUE_NUMBERS)
    TOUCHED_ISSUE_NUMBERS.clear()
    return touched


def get_issue_or_pr_snapshot(issue_number: int) -> dict | None:
    """Fetch issue metadata used for derived status labels."""
    result = github_api("GET", f"issues/{issue_number}")
    if isinstance(result, dict):
        return result
    return None


def get_issue_or_pr_labels(issue_number: int) -> set[str] | None:
    """Fetch the current label set for an issue or PR."""
    item = get_issue_or_pr_snapshot(issue_number)
    if not isinstance(item, dict):
        return None

    labels = item.get("labels", [])
    if not isinstance(labels, list):
        return set()

    result = set()
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
            if isinstance(name, str):
                result.add(name)
        elif isinstance(label, str):
            result.add(label)
    return result


def request_reviewer_assignment(issue_number: int, username: str) -> AssignmentAttempt:
    return github_api_module.request_reviewer_assignment(sys.modules[__name__], issue_number, username)


def assign_reviewer(issue_number: int, username: str) -> bool:
    return github_api_module.assign_reviewer(sys.modules[__name__], issue_number, username)


def get_assignment_failure_comment(reviewer: str, attempt: AssignmentAttempt) -> str | None:
    return github_api_module.get_assignment_failure_comment(sys.modules[__name__], reviewer, attempt)


def get_issue_assignees(issue_number: int) -> list[str]:
    return github_api_module.get_issue_assignees(sys.modules[__name__], issue_number)


def add_reaction(comment_id: int, reaction: str) -> bool:
    return github_api_module.add_reaction(sys.modules[__name__], comment_id, reaction)


def remove_assignee(issue_number: int, username: str) -> bool:
    return github_api_module.remove_assignee(sys.modules[__name__], issue_number, username)


def remove_pr_reviewer(issue_number: int, username: str) -> bool:
    return github_api_module.remove_pr_reviewer(sys.modules[__name__], issue_number, username)


def unassign_reviewer(issue_number: int, username: str) -> bool:
    return github_api_module.unassign_reviewer(sys.modules[__name__], issue_number, username)


def check_user_permission(username: str, required_permission: str = "triage") -> bool:
    return github_api_module.check_user_permission(sys.modules[__name__], username, required_permission)


# ==============================================================================
# State Management
# ==============================================================================


def get_state_issue() -> dict | None:
    return state_store_module.get_state_issue(sys.modules[__name__])


def default_state_issue_prefix() -> str:
    return state_store_module.default_state_issue_prefix()


def split_state_issue_body(body: str) -> StateIssueBodyParts:
    return state_store_module.split_state_issue_body(body)


def extract_fenced_block(inner_block: str, language_pattern: str) -> str | None:
    return state_store_module.extract_fenced_block(inner_block, language_pattern)


def normalize_lock_metadata(lock_meta: dict | None) -> dict:
    return state_store_module.normalize_lock_metadata(lock_meta)


def parse_state_yaml_from_issue_body(body: str) -> dict:
    return state_store_module.parse_state_yaml_from_issue_body(body)


def parse_lock_metadata_from_issue_body(body: str) -> dict:
    return state_store_module.parse_lock_metadata_from_issue_body(body)


def render_marked_fenced_block(
    start_marker: str,
    end_marker: str,
    language: str,
    content: str,
) -> str:
    return state_store_module.render_marked_fenced_block(start_marker, end_marker, language, content)


def render_state_issue_body(
    state: dict,
    lock_meta: dict,
    base_body: str | None = None,
    *,
    preserve_state_block: bool = False,
) -> str:
    return state_store_module.render_state_issue_body(
        state,
        lock_meta,
        base_body,
        preserve_state_block=preserve_state_block,
    )


def parse_state_from_issue(issue: dict) -> dict:
    return state_store_module.parse_state_from_issue(issue)


def get_state_issue_snapshot() -> StateIssueSnapshot | None:
    return state_store_module.get_state_issue_snapshot(sys.modules[__name__])


def conditional_patch_state_issue(body: str, etag: str | None = None) -> GitHubApiResult:
    return state_store_module.conditional_patch_state_issue(sys.modules[__name__], body, etag)


def assert_lock_held(operation: str) -> None:
    state_store_module.assert_lock_held(sys.modules[__name__], operation)


def load_state(*, fail_on_unavailable: bool = False) -> dict:
    return state_store_module.load_state(sys.modules[__name__], fail_on_unavailable=fail_on_unavailable)


def save_state(state: dict) -> bool:
    return state_store_module.save_state(sys.modules[__name__], state)


def parse_iso8601_timestamp(value: Any) -> datetime | None:
    return state_store_module.parse_iso8601_timestamp(value)


def lock_is_currently_valid(lock_meta: dict, now: datetime | None = None) -> bool:
    return lease_lock_module.lock_is_currently_valid(sys.modules[__name__], lock_meta, now)


def get_lock_owner_context() -> tuple[str, str, str]:
    return lease_lock_module.get_lock_owner_context()


def build_lock_metadata(
    lock_token: str,
    lock_owner_run_id: str,
    lock_owner_workflow: str,
    lock_owner_job: str,
) -> dict:
    return lease_lock_module.build_lock_metadata(
        sys.modules[__name__], lock_token, lock_owner_run_id, lock_owner_workflow, lock_owner_job
    )


def clear_lock_metadata() -> dict:
    return lease_lock_module.clear_lock_metadata(sys.modules[__name__])


def normalize_lock_ref_name(ref_name: str) -> str:
    return lease_lock_module.normalize_lock_ref_name(ref_name)


def get_lock_ref_name() -> str:
    return lease_lock_module.get_lock_ref_name(sys.modules[__name__])


def get_lock_ref_display() -> str:
    return lease_lock_module.get_lock_ref_display(sys.modules[__name__])


def get_state_issue_html_url() -> str:
    return lease_lock_module.get_state_issue_html_url(sys.modules[__name__])


def extract_ref_sha(payload: Any) -> str | None:
    return lease_lock_module.extract_ref_sha(payload)


def extract_commit_tree_sha(payload: Any) -> str | None:
    return lease_lock_module.extract_commit_tree_sha(payload)


def extract_commit_sha(payload: Any) -> str | None:
    return lease_lock_module.extract_commit_sha(payload)


def render_lock_commit_message(lock_meta: dict) -> str:
    return lease_lock_module.render_lock_commit_message(sys.modules[__name__], lock_meta)


def parse_lock_metadata_from_lock_commit_message(message: str) -> dict:
    return lease_lock_module.parse_lock_metadata_from_lock_commit_message(sys.modules[__name__], message)


def ensure_lock_ref_exists() -> str:
    return lease_lock_module.ensure_lock_ref_exists(sys.modules[__name__])


def get_lock_ref_snapshot() -> tuple[str, str, dict]:
    return lease_lock_module.get_lock_ref_snapshot(sys.modules[__name__])


def create_lock_commit(parent_sha: str, tree_sha: str, lock_meta: dict) -> GitHubApiResult:
    return lease_lock_module.create_lock_commit(sys.modules[__name__], parent_sha, tree_sha, lock_meta)


def cas_update_lock_ref(new_sha: str) -> GitHubApiResult:
    return lease_lock_module.cas_update_lock_ref(sys.modules[__name__], new_sha)


def ensure_state_issue_lease_lock_fresh() -> bool:
    return lease_lock_module.ensure_state_issue_lease_lock_fresh(sys.modules[__name__])


def renew_state_issue_lease_lock(context: LeaseContext) -> bool:
    return lease_lock_module.renew_state_issue_lease_lock(sys.modules[__name__], context)


def acquire_state_issue_lease_lock() -> LeaseContext:
    return lease_lock_module.acquire_state_issue_lease_lock(sys.modules[__name__])


def release_state_issue_lease_lock() -> bool:
    return lease_lock_module.release_state_issue_lease_lock(sys.modules[__name__])


def sync_members_with_queue(state: dict) -> tuple[dict, list[str]]:
    return queue_sync_members_with_queue(sys.modules[__name__], state)


def reposition_member_as_next(state: dict, username: str) -> bool:
    return queue_reposition_member_as_next(state, username)


def process_pass_until_expirations(state: dict) -> tuple[dict, list[str]]:
    return queue_process_pass_until_expirations(state)


# ==============================================================================
# Reviewer Assignment
# ==============================================================================


def get_next_reviewer(state: dict, skip_usernames: set[str] | None = None) -> str | None:
    return queue_get_next_reviewer(state, skip_usernames)


def record_assignment(state: dict, github: str, issue_number: int,
                     issue_type: str) -> None:
    queue_record_assignment(
        state,
        github,
        issue_number,
        issue_type,
        max_recent_assignments=MAX_RECENT_ASSIGNMENTS,
    )


# ==============================================================================
# Command Parsing & Handling
# ==============================================================================


def strip_code_blocks(comment_body: str) -> str:
    return commands_module.strip_code_blocks(comment_body)


def parse_command(comment_body: str) -> tuple[str, list[str]] | None:
    return commands_module.parse_command(sys.modules[__name__], comment_body)


def handle_pass_command(state: dict, issue_number: int, comment_author: str,
                       reason: str | None) -> tuple[str, bool]:
    return commands_module.handle_pass_command(sys.modules[__name__], state, issue_number, comment_author, reason)


def handle_pass_until_command(state: dict, issue_number: int, comment_author: str,
                              return_date: str, reason: str | None) -> tuple[str, bool]:
    return commands_module.handle_pass_until_command(sys.modules[__name__], state, issue_number, comment_author, return_date, reason)


def handle_label_command(issue_number: int, label_string: str) -> tuple[str, bool]:
    return commands_module.handle_label_command(sys.modules[__name__], issue_number, label_string)


def parse_issue_labels() -> list[str]:
    return commands_module.parse_issue_labels()


def run_command(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return commands_module.run_command(command, cwd, check=check)


def summarize_output(result: subprocess.CompletedProcess, limit: int = 20) -> str:
    return commands_module.summarize_output(result, limit=limit)


def list_changed_files(repo_root: Path) -> list[str]:
    return commands_module.list_changed_files(repo_root)


def get_default_branch() -> str:
    return commands_module.get_default_branch(sys.modules[__name__])


def find_open_pr_for_branch(branch: str) -> dict | None:
    return commands_module.find_open_pr_for_branch(sys.modules[__name__], branch)


def resolve_workflow_run_pr_number() -> int:
    return commands_module.resolve_workflow_run_pr_number(sys.modules[__name__])


def create_pull_request(branch: str, base: str, issue_number: int) -> dict | None:
    return commands_module.create_pull_request(sys.modules[__name__], branch, base, issue_number)


def handle_accept_no_fls_changes_command(issue_number: int, comment_author: str) -> tuple[str, bool]:
    return commands_module.handle_accept_no_fls_changes_command(sys.modules[__name__], issue_number, comment_author)


def handle_sync_members_command(state: dict) -> tuple[str, bool]:
    return commands_module.handle_sync_members_command(sys.modules[__name__], state)


def handle_queue_command(state: dict) -> tuple[str, bool]:
    return commands_module.handle_queue_command(sys.modules[__name__], state)


def handle_commands_command() -> tuple[str, bool]:
    return commands_module.handle_commands_command(sys.modules[__name__])


def handle_claim_command(state: dict, issue_number: int,
                        comment_author: str) -> tuple[str, bool]:
    return commands_module.handle_claim_command(sys.modules[__name__], state, issue_number, comment_author)


def handle_release_command(state: dict, issue_number: int,
                          comment_author: str, args: list | None = None) -> tuple[str, bool]:
    return commands_module.handle_release_command(sys.modules[__name__], state, issue_number, comment_author, args)


def handle_assign_command(state: dict, issue_number: int,
                         username: str) -> tuple[str, bool]:
    return commands_module.handle_assign_command(sys.modules[__name__], state, issue_number, username)


def handle_assign_from_queue_command(state: dict, issue_number: int) -> tuple[str, bool]:
    return commands_module.handle_assign_from_queue_command(sys.modules[__name__], state, issue_number)


# ==============================================================================
# Event Handlers
# ==============================================================================


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    return reviews_module.ensure_review_entry(state, issue_number, create=create)


def set_current_reviewer(state: dict, issue_number: int, reviewer: str,
                        assignment_method: str = "round-robin") -> None:
    reviews_module.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    return reviews_module.update_reviewer_activity(state, issue_number, reviewer)


def mark_review_complete(
    state: dict,
    issue_number: int,
    reviewer: str | None,
    source: str,
) -> bool:
    return reviews_module.mark_review_complete(state, issue_number, reviewer, source)


def is_triage_or_higher(username: str) -> bool:
    return reviews_module.is_triage_or_higher(sys.modules[__name__], username)


def trigger_mandatory_approver_escalation(state: dict, issue_number: int) -> bool:
    return reviews_module.trigger_mandatory_approver_escalation(sys.modules[__name__], state, issue_number)


def satisfy_mandatory_approver_requirement(
    state: dict,
    issue_number: int,
    approver: str,
) -> bool:
    return reviews_module.satisfy_mandatory_approver_requirement(
        sys.modules[__name__], state, issue_number, approver
    )


def handle_pr_approved_review(
    state: dict,
    issue_number: int,
    review_author: str,
    completion_source: str,
) -> bool:
    return reviews_module.handle_pr_approved_review(
        sys.modules[__name__], state, issue_number, review_author, completion_source
    )


def parse_github_timestamp(value: str | None) -> datetime | None:
    return reviews_module.parse_github_timestamp(value)


def get_pull_request_reviews(issue_number: int) -> list[dict] | None:
    return reviews_module.get_pull_request_reviews(sys.modules[__name__], issue_number)


def collapse_latest_reviews_by_login(reviews: list[dict]) -> dict[str, dict]:
    return reviews_module.collapse_latest_reviews_by_login(reviews)


def get_current_cycle_boundary(review_data: dict) -> datetime | None:
    return reviews_module.get_current_cycle_boundary(sys.modules[__name__], review_data)


def pr_has_current_write_approval(
    issue_number: int,
    review_data: dict,
    permission_cache: dict[str, bool] | None = None,
    reviews: list[dict] | None = None,
) -> bool | None:
    return reviews_module.pr_has_current_write_approval(
        sys.modules[__name__],
        issue_number,
        review_data,
        permission_cache=permission_cache,
        reviews=reviews,
    )


def project_status_labels_for_item(
    issue_number: int,
    state: dict,
    *,
    issue_snapshot: dict | None = None,
) -> tuple[set[str] | None, dict[str, str | None]]:
    return reviews_module.project_status_labels_for_item(
        sys.modules[__name__], issue_number, state, issue_snapshot=issue_snapshot
    )


def sync_status_labels(issue_number: int, desired_labels: set[str], actual_labels: Iterable[str]) -> bool:
    return reviews_module.sync_status_labels(sys.modules[__name__], issue_number, desired_labels, actual_labels)


def sync_status_labels_for_items(state: dict, issue_numbers: Iterable[int]) -> bool:
    return reviews_module.sync_status_labels_for_items(sys.modules[__name__], state, issue_numbers)


def list_open_items_with_status_labels() -> list[int]:
    return reviews_module.list_open_items_with_status_labels(sys.modules[__name__])


def get_latest_review_by_reviewer(reviews: list[dict], reviewer: str) -> dict | None:
    """Return the latest review authored by the given reviewer."""
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), -1)

    for index, review in enumerate(reviews):
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue

        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            submitted_at = datetime.min.replace(tzinfo=timezone.utc)

        review_key = (submitted_at, index)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review

    return latest_review


def find_triage_approval_after(
    reviews: list[dict],
    since: datetime | None,
) -> tuple[str, datetime] | None:
    """Find the first triage+ approval submitted after `since`."""
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[datetime, int, str]] = []

    for index, review in enumerate(reviews):
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue

        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue

        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue

        if since is not None and submitted_at <= since:
            continue

        approvals.append((submitted_at, index, author))

    approvals.sort(key=lambda item: (item[0], item[1]))

    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at

    return None


def reconcile_active_review_entry(
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    """Reconcile one active review entry from current GitHub PR review state.

    Returns (message, success, state_changed).
    """
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False

    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return (
            f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.",
            True,
            False,
        )

    if review_data.get("review_completed_at") and not review_data.get("mandatory_approver_required"):
        return f"ℹ️ Review for #{issue_number} is already marked complete; no changes made.", True, False

    if require_pull_request_context:
        is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
        if not is_pr:
            return (
                f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only "
                "reconciles PR reviews.",
                True,
                False,
            )

    reviews = get_pull_request_reviews(issue_number)
    if reviews is None:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False

    state_changed = False
    messages: list[str] = []

    latest_review = get_latest_review_by_reviewer(reviews, assigned_reviewer)
    if latest_review is None:
        messages.append(
            f"No review by assigned reviewer @{assigned_reviewer} was found on PR #{issue_number}."
        )
    else:
        latest_state = str(latest_review.get("state", "")).upper()
        if latest_state == "APPROVED":
            changed = handle_pr_approved_review(
                state,
                issue_number,
                assigned_reviewer,
                completion_source,
            )
            if changed:
                state_changed = True
                messages.append(
                    f"latest review by @{assigned_reviewer} is `APPROVED`; applied approval transitions"
                )
            else:
                messages.append(
                    f"latest review by @{assigned_reviewer} is `APPROVED`, but state already reflected it"
                )
        elif latest_state in {"COMMENTED", "CHANGES_REQUESTED"}:
            changed = update_reviewer_activity(state, issue_number, assigned_reviewer)
            if changed:
                state_changed = True
                messages.append(
                    f"latest review by @{assigned_reviewer} is `{latest_state}`; refreshed reviewer activity"
                )
            else:
                messages.append(
                    f"latest assigned-reviewer state is `{latest_state}` and no update was needed"
                )
        else:
            state_name = latest_state or "UNKNOWN"
            messages.append(
                f"latest review by @{assigned_reviewer} is `{state_name}` and no reconciliation transition applies"
            )

    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data and review_data.get("mandatory_approver_required"):
        escalation_opened_at = (
            parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at"))
            or parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        )
        triage_approval = find_triage_approval_after(reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")

    if state_changed:
        detail = "; ".join(messages) if messages else "applied state reconciliation transitions"
        return f"✅ Rectified PR #{issue_number}: {detail}.", True, True

    detail = "; ".join(messages) if messages else "no reconciliation transitions applied"
    return f"ℹ️ Rectify checked PR #{issue_number}: {detail}.", True, False


def handle_rectify_command(state: dict, issue_number: int, comment_author: str) -> tuple[str, bool, bool]:
    """Handle /rectify for the current issue/PR only.

    Permission model:
    - Allowed for the currently assigned reviewer.
    - Allowed for users with triage+ permissions.

    Returns (message, success, state_changed).
    """
    review_data = ensure_review_entry(state, issue_number)
    current_reviewer = review_data.get("current_reviewer") if review_data else None

    is_current_reviewer = (
        isinstance(current_reviewer, str)
        and current_reviewer.lower() == comment_author.lower()
    )

    has_triage = False
    if not is_current_reviewer:
        has_triage = check_user_permission(comment_author, "triage")

    if not is_current_reviewer and not has_triage:
        if current_reviewer:
            return (
                f"❌ Only the assigned reviewer (@{current_reviewer}) or a maintainer with triage+ "
                "permission can run `/rectify`.",
                False,
                False,
            )
        return (
            "❌ Only maintainers with triage+ permission can run `/rectify` when no assigned "
            "reviewer is tracked.",
            False,
            False,
        )

    return reconcile_active_review_entry(state, issue_number)


def check_overdue_reviews(state: dict) -> list[dict]:
    """
    Check all active reviews for overdue ones.
    
    Returns a list of overdue reviews with their status:
    [
        {
            "issue_number": 123,
            "reviewer": "username",
            "days_overdue": 5,
            "needs_warning": True,  # First warning needed
            "needs_transition": False,  # 28 days passed, transition needed
        },
        ...
    ]
    """
    if "active_reviews" not in state:
        return []
    
    now = datetime.now(timezone.utc)
    overdue = []
    
    for issue_key, review_data in state["active_reviews"].items():
        if not isinstance(review_data, dict):
            continue

        if review_data.get("review_completed_at"):
            continue
        
        current_reviewer = review_data.get("current_reviewer")
        if not current_reviewer:
            continue
        
        last_activity = review_data.get("last_reviewer_activity")
        if not last_activity:
            # No activity recorded, use assigned_at
            last_activity = review_data.get("assigned_at")
        if not last_activity:
            continue
        
        # Parse the timestamp
        try:
            last_activity_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        
        days_since_activity = (now - last_activity_dt).days
        
        if days_since_activity < REVIEW_DEADLINE_DAYS:
            continue  # Not overdue yet
        
        # Check if we've already sent a warning
        transition_warning_sent = review_data.get("transition_warning_sent")
        
        if transition_warning_sent:
            # Warning already sent - check if transition period has passed
            try:
                warning_dt = datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
                days_since_warning = (now - warning_dt).days
                
                if days_since_warning >= TRANSITION_PERIOD_DAYS:
                    overdue.append({
                        "issue_number": int(issue_key),
                        "reviewer": current_reviewer,
                        "days_overdue": days_since_activity,
                        "days_since_warning": days_since_warning,
                        "needs_warning": False,
                        "needs_transition": True,
                    })
            except (ValueError, AttributeError):
                pass
        else:
            # First warning needed
            overdue.append({
                "issue_number": int(issue_key),
                "reviewer": current_reviewer,
                "days_overdue": days_since_activity - REVIEW_DEADLINE_DAYS,
                "days_since_warning": 0,
                "needs_warning": True,
                "needs_transition": False,
            })
    
    return overdue


def handle_overdue_review_warning(state: dict, issue_number: int, reviewer: str) -> bool:
    """
    Post a warning comment and record that we've warned the reviewer.
    
    Returns True if warning was posted, False otherwise.
    """
    issue_key = str(issue_number)
    
    if "active_reviews" not in state or issue_key not in state["active_reviews"]:
        return False
    
    review_data = state["active_reviews"][issue_key]
    if not isinstance(review_data, dict):
        return False
    
    # Post warning comment
    warning_message = f"""⚠️ **Review Reminder**

Hey @{reviewer}, it's been more than {REVIEW_DEADLINE_DAYS} days since you were assigned to review this.

**Please take one of the following actions:**

1. **Begin your review** - Post a comment with your feedback
2. **Pass the review** - Use `{BOT_MENTION} /pass [reason]` to assign the next reviewer
3. **Step away temporarily** - Use `{BOT_MENTION} /away YYYY-MM-DD [reason]` if you need time off

If no action is taken within {TRANSITION_PERIOD_DAYS} days, you may be transitioned from Producer to Observer status per our [contribution guidelines](CONTRIBUTING.md#review-deadlines).

_Life happens! If you're dealing with something, just let us know._"""
    
    post_comment(issue_number, warning_message)
    
    # Record that we've sent the warning
    now = datetime.now(timezone.utc).isoformat()
    review_data["transition_warning_sent"] = now
    
    print(f"Posted overdue warning for #{issue_number} to @{reviewer}")
    return True


def handle_transition_notice(state: dict, issue_number: int, reviewer: str) -> bool:
    """
    Post a notice that the transition period has ended.
    
    This does NOT automatically change their status - that requires manual intervention.
    Returns True if notice was posted, False otherwise.
    """
    # Post transition notice
    notice_message = f"""🔔 **Transition Period Ended**

@{reviewer}, the {TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

**The review will now be reassigned to the next person in the queue.**

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    
    post_comment(issue_number, notice_message)
    
    print(f"Posted transition notice for #{issue_number} to @{reviewer}")
    return True


def handle_issue_or_pr_opened(state: dict) -> bool:
    """
    Handle when an issue or PR is opened with a review label.

    Returns True if we took action, False otherwise.
    """
    assert_lock_held("handle_issue_or_pr_opened")

    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    print(f"Processing opened event for #{issue_number}")
    collect_touched_item(issue_number)

    # Check if already has a reviewer (check our tracked state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    
    current_assignees = get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers/assignees: {current_assignees}")
        return False

    # Check for review labels
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    print(f"ISSUE_LABELS env: {labels_json}")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        print("Failed to parse ISSUE_LABELS as JSON")
        labels = []

    if not any(label in REVIEW_LABELS for label in labels):
        print(
            f"Issue #{issue_number} does not have review labels {sorted(REVIEW_LABELS)} "
            f"(labels: {labels})"
        )
        return False

    # Get issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer
    reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not reviewer:
        post_comment(issue_number,
                    f"⚠️ No reviewers available in the queue. "
                    f"Please use `{BOT_MENTION} /sync-members` to update the queue.")
        return False

    # Assign the reviewer.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, reviewer)
    
    # Track the reviewer in our state (source of truth for pass command)
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    failure_comment = get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        post_comment(issue_number, failure_comment)

    # Post guidance comment
    if is_pr:
        if assignment_attempt.success:
            guidance = get_pr_guidance(reviewer, issue_author)
            post_comment(issue_number, guidance)
    else:
        if FLS_AUDIT_LABEL in labels:
            guidance = get_fls_audit_guidance(reviewer, issue_author)
        else:
            guidance = get_issue_guidance(reviewer, issue_author)
        post_comment(issue_number, guidance)

    return True


def handle_labeled_event(state: dict) -> bool:
    """
    Handle when an issue or PR is labeled with a review label.

    We already know from LABEL_NAME that the correct label was added,
    so we skip the label check that handle_issue_or_pr_opened does.
    """
    assert_lock_held("handle_labeled_event")

    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    label_name = os.environ.get("LABEL_NAME", "")
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    collect_touched_item(issue_number)

    if label_name == "sign-off: create pr":
        if is_pr:
            print("Sign-off label applied to PR; ignoring")
            return False
        review_data = ensure_review_entry(state, issue_number)
        reviewer = None
        if review_data:
            reviewer = review_data.get("current_reviewer")
        return mark_review_complete(
            state,
            issue_number,
            reviewer,
            "issue_label: sign-off: create pr",
        )

    if label_name not in REVIEW_LABELS:
        print(f"Label '{label_name}' is not a review label, skipping")
        return False

    # Check if already has a reviewer (check our tracked state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    
    current_assignees = get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers: {current_assignees}")
        return False

    print(f"Processing labeled event for #{issue_number}, author: {os.environ.get('ISSUE_AUTHOR', '')}")

    # Get issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer
    reviewer = get_next_reviewer(state, skip_usernames=skip_set)
    print(f"Selected reviewer for #{issue_number}: {reviewer}")

    if not reviewer:
        post_comment(issue_number,
                    f"⚠️ No reviewers available in the queue. "
                    f"Please use `{BOT_MENTION} /sync-members` to update the queue.")
        return False

    # Assign the reviewer.
    assignment_attempt = request_reviewer_assignment(issue_number, reviewer)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    failure_comment = get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        post_comment(issue_number, failure_comment)

    # Post guidance comment
    if is_pr:
        if assignment_attempt.success:
            guidance = get_pr_guidance(reviewer, issue_author)
            post_comment(issue_number, guidance)
    else:
        if label_name == FLS_AUDIT_LABEL:
            guidance = get_fls_audit_guidance(reviewer, issue_author)
        else:
            guidance = get_issue_guidance(reviewer, issue_author)
        post_comment(issue_number, guidance)

    return True


def handle_pull_request_review_event(state: dict) -> bool:
    """Handle submitted PR reviews for activity and completion tracking."""
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    review_state = os.environ.get("REVIEW_STATE", "").strip().upper()
    review_author = os.environ.get("REVIEW_AUTHOR", "").strip()
    if not review_state or not review_author:
        print("Missing review context")
        return False

    collect_touched_item(issue_number)

    review_action = os.environ.get("EVENT_ACTION", "").strip().lower()

    is_cross_repo = os.environ.get("PR_IS_CROSS_REPOSITORY", "false").lower() == "true"
    if is_cross_repo:
        print(
            "Deferring cross-repo pull_request_review reconciliation for "
            f"#{issue_number}: this event may have read-only permissions. "
            "A trusted workflow_run reconcile will persist state after this run succeeds. "
            "If needed, use `@guidelines-bot /rectify` as manual fallback."
        )
        return False

    assert_lock_held("handle_pull_request_review_event")

    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        print(f"No active review entry for #{issue_number}")
        return False

    current_reviewer = review_data.get("current_reviewer")
    if review_action == "dismissed" or review_state == "DISMISSED":
        print(f"Observed dismissed review on #{issue_number}; deferring to status-label projection")
        return False

    if review_state == "APPROVED":
        return handle_pr_approved_review(
            state,
            issue_number,
            review_author,
            "pull_request_review",
        )

    if review_state in {"COMMENTED", "CHANGES_REQUESTED"}:
        if not current_reviewer or current_reviewer.lower() != review_author.lower():
            print(
                f"Ignoring review from @{review_author} on #{issue_number}; "
                f"current reviewer is @{current_reviewer}"
            )
            return False
        return update_reviewer_activity(state, issue_number, review_author)

    print(f"Ignoring review state '{review_state}' for #{issue_number}")
    return False


def handle_workflow_run_event(state: dict) -> bool:
    """Handle trusted second-hop workflow_run reconciliation."""
    assert_lock_held("handle_workflow_run_event")

    workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
    workflow_run_event_action = os.environ.get("WORKFLOW_RUN_EVENT_ACTION", "").strip().lower()
    if workflow_run_event != "pull_request_review":
        observed = workflow_run_event or "<missing>"
        print(
            "Ignoring workflow_run reconcile event with unsupported source event: "
            f"{observed}"
        )
        return False

    if workflow_run_event_action not in {"submitted", "dismissed"}:
        observed = workflow_run_event_action or "<missing>"
        print(
            "Ignoring workflow_run reconcile event with unsupported source action: "
            f"{observed}"
        )
        return False

    issue_number = resolve_workflow_run_pr_number()
    collect_touched_item(issue_number)

    if workflow_run_event_action == "dismissed":
        print(f"Workflow_run observed dismissed review for #{issue_number}; projecting labels only")
        return False

    message, success, state_changed = reconcile_active_review_entry(
        state,
        issue_number,
        require_pull_request_context=False,
        completion_source="workflow_run:pull_request_review",
    )
    print(message)

    if not success:
        raise RuntimeError(
            f"Workflow_run reconcile failed for pull request #{issue_number}: {message}"
        )

    if state_changed and not post_comment(issue_number, message):
        print(
            "WARNING: Workflow_run reconcile changed state but failed to post "
            f"comment on pull request #{issue_number}.",
            file=sys.stderr,
        )

    return state_changed


def handle_closed_event(state: dict) -> bool:
    """
    Handle when an issue or PR is closed.
    
    Cleans up the active_reviews entry to prevent state from growing indefinitely.

    Returns True if we modified state, False otherwise.
    """
    assert_lock_held("handle_closed_event")

    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found for closed event")
        return False

    collect_touched_item(issue_number)

    issue_key = str(issue_number)
    
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        print(f"Cleaned up active_reviews entry for #{issue_number}")
        return True
    
    print(f"No active_reviews entry found for #{issue_number}")
    return False


def handle_comment_event(state: dict) -> bool:
    """
    Handle a comment event - check for bot commands and track reviewer activity.

    Returns True if we took action, False otherwise.
    """
    assert_lock_held("handle_comment_event")

    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_id = os.environ.get("COMMENT_ID", "")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))

    if not comment_body or not issue_number:
        return False

    # Check if comment author is the current reviewer - if so, update their activity
    # This resets the 14-day deadline clock
    activity_updated = update_reviewer_activity(state, issue_number, comment_author)
    
    # Parse for bot command
    sanitized_body = strip_code_blocks(comment_body)
    parsed = parse_command(sanitized_body)
    if not parsed:
        # No bot command, but we may have updated activity
        return activity_updated

    command, args = parsed
    print(f"Parsed command: {command}, args: {args}")

    response = ""
    success = False
    state_changed = False
    status_projection_commands = {"pass", "away", "claim", "release", "rectify", "r?-user", "assign-from-queue"}

    if command == "_multiple_commands":
        response = ("⚠️ Multiple bot commands in one comment are ignored. "
                    "Please post a single command per comment. "
                    f"For a list of commands, use `{BOT_MENTION} /commands`.")
        success = False
    # Handle each command
    elif command == "pass":
        reason = " ".join(args) if args else None
        response, success = handle_pass_command(state, issue_number, comment_author, reason)
        state_changed = success

    elif command == "away":
        if not args:
            response = (f"❌ Missing date. Usage: `{BOT_MENTION} /away YYYY-MM-DD [reason]`")
            success = False
        else:
            return_date = args[0]
            reason = " ".join(args[1:]) if len(args) > 1 else None
            response, success = handle_pass_until_command(
                state, issue_number, comment_author, return_date, reason
            )
            state_changed = success

    elif command == "label":
        if not args:
            response = (f"❌ Missing label. Usage: `{BOT_MENTION} /label +label-name` or "
                       f"`{BOT_MENTION} /label -label-name`")
            success = False
        else:
            # Rejoin all args to handle labels with spaces
            # Then parse for +label and -label patterns
            full_arg = " ".join(args)
            response, success = handle_label_command(issue_number, full_arg)

    elif command == "accept-no-fls-changes":
        response, success = handle_accept_no_fls_changes_command(issue_number, comment_author)

    elif command == "sync-members":
        response, success = handle_sync_members_command(state)
        state_changed = success

    elif command == "queue":
        response, success = handle_queue_command(state)

    elif command == "commands":
        response, success = handle_commands_command()

    elif command == "claim":
        response, success = handle_claim_command(state, issue_number, comment_author)
        state_changed = success

    elif command == "release":
        # Pass args to handle_release_command for @username parsing
        response, success = handle_release_command(state, issue_number, comment_author, args)
        state_changed = success

    elif command == "rectify":
        response, success, state_changed = handle_rectify_command(
            state,
            issue_number,
            comment_author,
        )

    elif command == "r?-user":
        # Handle "/r? @username" - assign specific user
        username = args[0] if args else ""
        response, success = handle_assign_command(state, issue_number, username)
        state_changed = success

    elif command == "assign-from-queue":
        # Handle "/r? producers" - assign next from round-robin queue
        response, success = handle_assign_from_queue_command(state, issue_number)
        state_changed = success

    elif command == "r?":
        # Handle "/r?" with no target - show usage error
        response = (f"❌ Missing target. Usage:\n"
                   f"- `{BOT_MENTION} /r? @username` - Assign a specific reviewer\n"
                   f"- `{BOT_MENTION} /r? producers` - Assign next reviewer from queue")
        success = False

    elif command == "_malformed_known":
        # User typed a known command but forgot the / prefix
        attempted = args[0] if args else "command"
        response = (f"⚠️ Did you mean `{BOT_MENTION} /{attempted}`?\n\n"
                   f"Commands require a `/` prefix.")
        success = False

    elif command == "_malformed_unknown":
        # User typed something after @guidelines-bot but it's not a known command
        attempted = args[0] if args else ""
        response = (f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\n"
                   f"Try `{BOT_MENTION} /commands` to see available commands.")
        success = False

    else:
        response = (f"❌ Unknown command: `/{command}`\n\n"
                   f"Available commands:\n{get_commands_help()}")
        success = False

    if command in status_projection_commands:
        collect_touched_item(issue_number)

    # React to the command comment
    if comment_id and command != "_multiple_commands":
        add_reaction(int(comment_id), "eyes")
        if success:
            add_reaction(int(comment_id), "+1")

    # Post response
    if response:
        post_comment(issue_number, response)

    return state_changed


def handle_manual_dispatch(state: dict) -> bool:
    """Handle manual workflow dispatch."""
    action = os.environ.get("MANUAL_ACTION", "")

    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False

    assert_lock_held("handle_manual_dispatch")

    if action == "sync-members":
        state, changes = sync_members_with_queue(state)
        if changes:
            print(f"Sync changes: {changes}")
        return True

    elif action == "repair-review-status-labels":
        tracked_numbers = []
        active_reviews = state.get("active_reviews", {})
        if isinstance(active_reviews, dict):
            for issue_key in active_reviews:
                try:
                    tracked_numbers.append(int(issue_key))
                except (TypeError, ValueError):
                    continue

        for issue_number in tracked_numbers:
            collect_touched_item(issue_number)
        for issue_number in list_open_items_with_status_labels():
            collect_touched_item(issue_number)
        print(f"Collected {len(TOUCHED_ISSUE_NUMBERS)} item(s) for status-label repair")
        return False

    elif action == "check-overdue":
        # Manually trigger the overdue review check
        return handle_scheduled_check(state)

    return False


def handle_scheduled_check(state: dict) -> bool:
    """
    Handle the scheduled (nightly) check for overdue reviews.
    
    This function:
    1. Checks all active reviews for overdue ones
    2. Posts warnings for reviews that are 14+ days overdue
    3. Posts transition notices and reassigns for 28+ days overdue

    Returns True if any action was taken, False otherwise.
    """
    assert_lock_held("handle_scheduled_check")

    print("Running scheduled check for overdue reviews...")
    
    overdue_reviews = check_overdue_reviews(state)
    
    if not overdue_reviews:
        print("No overdue reviews found.")
        return False
    
    print(f"Found {len(overdue_reviews)} overdue review(s)")
    
    state_changed = False
    
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        
        if review["needs_warning"]:
            # First warning - 14 days overdue
            print(f"Sending warning for #{issue_number} to @{reviewer} "
                  f"({review['days_overdue']} days overdue)")
            if handle_overdue_review_warning(state, issue_number, reviewer):
                state_changed = True
        
        elif review["needs_transition"]:
            # Transition period ended - 28 days total
            print(f"Transition period ended for #{issue_number}, @{reviewer} "
                  f"({review['days_since_warning']} days since warning)")
            
            # Post the transition notice
            handle_transition_notice(state, issue_number, reviewer)
            
            # Reassign to next in queue
            issue_key = str(issue_number)
            review_data = state["active_reviews"].get(issue_key, {})
            skipped = review_data.get("skipped", [])
            
            # Get issue author to skip
            # Note: We don't have easy access to issue author here, so we'll skip the current reviewer
            skip_set = set(skipped) | {reviewer}
            
            next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)
            
            if next_reviewer:
                # Unassign old reviewer
                unassign_reviewer(issue_number, reviewer)
                
                # Assign new reviewer
                assignment_attempt = request_reviewer_assignment(issue_number, next_reviewer)
                set_current_reviewer(state, issue_number, next_reviewer)
                
                # Track the skip
                if issue_key in state["active_reviews"]:
                    if reviewer not in state["active_reviews"][issue_key].get("skipped", []):
                        state["active_reviews"][issue_key]["skipped"].append(reviewer)
                
                # Post assignment comment (assume issue since we don't track type here)
                failure_comment = get_assignment_failure_comment(next_reviewer, assignment_attempt)
                if failure_comment:
                    post_comment(issue_number, failure_comment)

                guidance = get_issue_guidance(next_reviewer, "the contributor")
                post_comment(issue_number, guidance)
                
                # Record assignment
                record_assignment(state, next_reviewer, issue_number, "issue")
                
                print(f"Reassigned #{issue_number} from @{reviewer} to @{next_reviewer}")
            else:
                print(f"No available reviewers to reassign #{issue_number}")

            collect_touched_item(issue_number)
            state_changed = True
    
    return state_changed


# ==============================================================================
# Main
# ==============================================================================


def classify_event_intent(event_name: str, event_action: str) -> str:
    return app_module.classify_event_intent(sys.modules[__name__], event_name, event_action)


def event_requires_lease_lock(event_name: str, event_action: str) -> bool:
    """Backwards-compatible helper for tests and call sites."""
    return app_module.event_requires_lease_lock(sys.modules[__name__], event_name, event_action)


def main():
    app_module.main(sys.modules[__name__])


if __name__ == "__main__":
    main()
