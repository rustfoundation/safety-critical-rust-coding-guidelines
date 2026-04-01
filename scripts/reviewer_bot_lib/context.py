"""Typed runtime context for extracted reviewer-bot modules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .config import AssignmentAttempt, GitHubApiResult, LeaseContext, StateIssueSnapshot
from .lifecycle import HeadObservationRepairResult


@dataclass(frozen=True)
class EventContext:
    event_name: str
    event_action: str
    issue_number: int | None = None
    is_pull_request: bool | None = None
    issue_author: str | None = None
    issue_state: str | None = None
    issue_labels: tuple[str, ...] = ()
    comment_id: int | None = None
    comment_author: str | None = None
    comment_body: str | None = None
    comment_source_event_key: str | None = None
    pr_is_cross_repository: bool | None = None
    review_author: str | None = None
    review_state: str | None = None
    workflow_run_event: str | None = None
    workflow_run_event_action: str | None = None
    workflow_run_head_sha: str | None = None
    workflow_run_reconcile_pr_number: int | None = None
    workflow_run_reconcile_head_sha: str | None = None
    workflow_run_id: int | None = None
    workflow_name: str | None = None
    workflow_job_name: str | None = None
    manual_action: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    state_changed: bool
    release_failed: bool = False


@dataclass(frozen=True)
class CommentEventRequest:
    issue_number: int
    is_pull_request: bool
    issue_state: str = ""
    issue_author: str = ""
    comment_id: int = 0
    comment_author: str = ""
    comment_author_id: int = 0
    comment_body: str = ""
    comment_created_at: str = ""
    comment_source_event_key: str = ""
    comment_user_type: str = ""
    comment_sender_type: str = ""
    comment_installation_id: str = ""
    comment_performed_via_github_app: bool = False


@dataclass(frozen=True)
class PrCommentTrustContext:
    github_repository: str = ""
    comment_author_association: str = ""
    current_workflow_file: str = ""
    github_ref: str = ""
    github_run_id: int = 0
    github_run_attempt: int = 0


@dataclass(frozen=True)
class AssignmentRequest:
    issue_number: int
    issue_author: str = ""
    is_pull_request: bool = False
    issue_labels: tuple[str, ...] = ()
    repo_owner: str = ""
    repo_name: str = ""


@dataclass(frozen=True)
class PrivilegedCommandRequest:
    issue_number: int
    actor: str = ""
    command_name: str = ""
    is_pull_request: bool = False
    issue_labels: tuple[str, ...] = ()
    target_repo_root: str = ""
    workflow_run_reconcile_pr_number: int | None = None
    workflow_run_reconcile_head_sha: str = ""
    workflow_run_head_sha: str = ""


@runtime_checkable
class GitHubTransportContext(Protocol):
    """GitHub API transport and mutation surface used by low-level helpers."""

    LOCK_API_RETRY_LIMIT: int
    LOCK_RETRY_BASE_SECONDS: float
    REVIEWER_REQUEST_422_TEMPLATE: str
    AssignmentAttempt: type[AssignmentAttempt]
    GitHubApiResult: type[GitHubApiResult]

    def get_github_token(self) -> str: ...
    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str: ...
    def github_api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        extra_headers: dict[str, str] | None = None,
        *,
        retry_policy: str = "none",
        timeout_seconds: float | None = None,
        suppress_error_log: bool = False,
    ) -> GitHubApiResult: ...
    def github_api(self, method: str, endpoint: str, data: dict | None = None) -> Any | None: ...
    def github_graphql_request(
        self,
        query: str,
        variables: dict | None = None,
        *,
        token: str | None = None,
        retry_policy: str = "none",
        timeout_seconds: float | None = None,
        suppress_error_log: bool = False,
    ) -> GitHubApiResult: ...
    def github_graphql(
        self,
        query: str,
        variables: dict | None = None,
        *,
        token: str | None = None,
    ) -> Any | None: ...
    def request_reviewer_assignment(self, issue_number: int, username: str) -> AssignmentAttempt: ...
    def get_user_permission_status(self, username: str, required_permission: str = "triage") -> str: ...
    def remove_assignee(self, issue_number: int, username: str) -> bool: ...
    def remove_pr_reviewer(self, issue_number: int, username: str) -> bool: ...


@runtime_checkable
class StateStoreContext(Protocol):
    """State issue and serialization surface used by state-store helpers."""

    ACTIVE_LEASE_CONTEXT: LeaseContext | None
    STATE_ISSUE_NUMBER: int
    STATE_READ_RETRY_LIMIT: int
    STATE_READ_RETRY_BASE_SECONDS: float
    LOCK_API_RETRY_LIMIT: int
    LOCK_RETRY_BASE_SECONDS: float
    GitHubApiResult: type[GitHubApiResult]
    sys: Any

    def github_api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        extra_headers: dict[str, str] | None = None,
        *,
        retry_policy: str = "none",
        timeout_seconds: float | None = None,
        suppress_error_log: bool = False,
    ) -> GitHubApiResult: ...
    def get_state_issue(self) -> dict | None: ...
    def get_state_issue_snapshot(self) -> StateIssueSnapshot | None: ...
    def conditional_patch_state_issue(self, body: str, etag: str | None = None) -> GitHubApiResult: ...
    def parse_lock_metadata_from_issue_body(self, body: str) -> dict: ...
    def render_state_issue_body(
        self,
        state: dict,
        lock_meta: dict,
        base_body: str | None = None,
        *,
        preserve_state_block: bool = False,
    ) -> str: ...
    def assert_lock_held(self, operation: str) -> None: ...
    def parse_iso8601_timestamp(self, value: Any) -> datetime | None: ...
    def normalize_lock_metadata(self, lock_meta: dict | None) -> dict: ...
    def ensure_state_issue_lease_lock_fresh(self) -> bool: ...


@runtime_checkable
class LeaseLockContext(Protocol):
    """Lock-specific runtime surface used by lease-lock helpers."""

    ACTIVE_LEASE_CONTEXT: LeaseContext | None
    LOCK_API_RETRY_LIMIT: int
    LOCK_RETRY_BASE_SECONDS: float
    LOCK_LEASE_TTL_SECONDS: int
    LOCK_MAX_WAIT_SECONDS: int
    LOCK_RENEWAL_WINDOW_SECONDS: int
    LOCK_REF_NAME: str
    LOCK_REF_BOOTSTRAP_BRANCH: str
    LOCK_COMMIT_MARKER: str
    LOCK_SCHEMA_VERSION: int
    LeaseContext: type[LeaseContext]
    sys: Any

    def parse_iso8601_timestamp(self, value: Any) -> datetime | None: ...
    def normalize_lock_metadata(self, lock_meta: dict | None) -> dict: ...
    def clear_lock_metadata(self) -> dict: ...
    def get_state_issue_snapshot(self) -> StateIssueSnapshot | None: ...
    def github_api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        extra_headers: dict[str, str] | None = None,
        *,
        retry_policy: str = "none",
        timeout_seconds: float | None = None,
        suppress_error_log: bool = False,
    ) -> GitHubApiResult: ...
    def get_lock_ref_display(self) -> str: ...
    def get_state_issue_html_url(self) -> str: ...
    def get_lock_ref_snapshot(self) -> tuple[str, str, dict]: ...
    def build_lock_metadata(
        self,
        lock_token: str,
        lock_owner_run_id: str,
        lock_owner_workflow: str,
        lock_owner_job: str,
    ) -> dict: ...
    def create_lock_commit(self, parent_sha: str, tree_sha: str, lock_meta: dict) -> GitHubApiResult: ...
    def cas_update_lock_ref(self, new_sha: str) -> GitHubApiResult: ...
    def lock_is_currently_valid(self, lock_meta: dict, now: datetime | None = None) -> bool: ...
    def renew_state_issue_lease_lock(self, context: LeaseContext) -> bool: ...


@runtime_checkable
class ReviewerBotContext(GitHubTransportContext, StateStoreContext, LeaseLockContext, Protocol):
    """Broader runtime surface expected by orchestration-heavy extracted modules.

    This protocol intentionally captures true runtime services and shared state,
    not pure helper modules or formatting helpers that should be imported
    directly where used.
    """

    EVENT_INTENT_MUTATING: str
    EVENT_INTENT_NON_MUTATING_DEFER: str
    EVENT_INTENT_NON_MUTATING_READONLY: str
    datetime: type[datetime]
    timezone: Any
    def load_state(self, *, fail_on_unavailable: bool = False) -> dict: ...
    def save_state(self, state: dict) -> bool: ...
    def ensure_state_issue_lease_lock_fresh(self) -> bool: ...
    def acquire_state_issue_lease_lock(self) -> LeaseContext: ...
    def release_state_issue_lease_lock(self) -> bool: ...
    def drain_touched_items(self) -> list[int]: ...
    def process_pass_until_expirations(self, state: dict) -> tuple[dict, list[str]]: ...
    def sync_members_with_queue(self, state: dict) -> tuple[dict, list[str]]: ...
    def handle_issue_or_pr_opened(self, state: dict) -> bool: ...
    def handle_labeled_event(self, state: dict) -> bool: ...
    def handle_issue_edited_event(self, state: dict) -> bool: ...
    def handle_closed_event(self, state: dict) -> bool: ...
    def handle_pull_request_target_synchronize(self, state: dict) -> bool: ...
    def handle_pull_request_review_event(self, state: dict) -> bool: ...
    def handle_comment_event(self, state: dict) -> bool: ...
    def handle_manual_dispatch(self, state: dict) -> bool: ...
    def handle_scheduled_check(self, state: dict) -> bool: ...
    def handle_workflow_run_event(self, state: dict) -> bool: ...
    def maybe_record_head_observation_repair(
        self, issue_number: int, review_data: dict
    ) -> HeadObservationRepairResult: ...
    def sync_status_labels_for_items(self, state: dict, issue_numbers: Iterable[int]) -> bool: ...
    def compute_reviewer_response_state(
        self,
        issue_number: int,
        review_data: dict,
        *,
        issue_snapshot: dict | None = None,
        pull_request: dict | None = None,
        reviews: list[dict] | None = None,
    ) -> dict[str, object]: ...
