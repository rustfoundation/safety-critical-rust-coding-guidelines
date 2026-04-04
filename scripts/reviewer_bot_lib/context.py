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


@dataclass(frozen=True)
class ManualDispatchRequest:
    action: str = ""
    issue_number: int | None = None
    privileged_source_event_key: str = ""


@dataclass(frozen=True)
class IssueLifecycleRequest:
    issue_number: int = 0
    is_pull_request: bool = False
    issue_labels: tuple[str, ...] = ()
    issue_author: str = ""
    sender_login: str = ""
    updated_at: str = ""
    issue_title: str = ""
    issue_body: str = ""
    previous_title: str = ""
    previous_body: str = ""
    pr_head_sha: str = ""
    event_created_at: str = ""


@dataclass(frozen=True)
class LabelEventRequest:
    issue_number: int = 0
    is_pull_request: bool = False
    label_name: str = ""


@dataclass(frozen=True)
class PullRequestSyncRequest:
    issue_number: int = 0
    head_sha: str = ""
    event_created_at: str = ""


@runtime_checkable
class ConfigProvider(Protocol):
    def get(self, name: str, default: str = "") -> str: ...

    def set(self, name: str, value: Any) -> None: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class Sleeper(Protocol):
    def sleep(self, seconds: float) -> None: ...


@runtime_checkable
class JitterSource(Protocol):
    def uniform(self, lower: float, upper: float) -> float: ...


@runtime_checkable
class UuidSource(Protocol):
    def uuid4_hex(self) -> str: ...


@runtime_checkable
class Logger(Protocol):
    def event(self, level: str, message: str, **fields: Any) -> None: ...


@runtime_checkable
class RestTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any: ...


@runtime_checkable
class GraphQLTransport(Protocol):
    def query(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        query: str,
        variables: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any: ...


@runtime_checkable
class ArtifactDownloadTransport(Protocol):
    def download(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any: ...


@runtime_checkable
class EventInputsContext(Protocol):
    def get_config_value(self, name: str, default: str = "") -> str: ...


@runtime_checkable
class EventHandlerContext(Protocol):
    logger: Logger

    def get_config_value(self, name: str, default: str = "") -> str: ...

    def collect_touched_item(self, issue_number: int | None) -> None: ...


@runtime_checkable
class ProjectBoardMetadataContext(Protocol):
    def get_config_value(self, name: str, default: str = "") -> str: ...

    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str: ...

    def github_graphql(
        self,
        query: str,
        variables: dict | None = None,
        *,
        token: str | None = None,
    ) -> Any | None: ...


@runtime_checkable
class ProjectBoardProjectionContext(Protocol):
    def get_issue_or_pr_snapshot(self, issue_number: int) -> dict | None: ...

    def compute_reviewer_response_state(
        self,
        issue_number: int,
        review_data: dict,
        *,
        issue_snapshot: dict | None = None,
    ) -> dict: ...


@runtime_checkable
class AppEventContextRuntime(Protocol):
    EVENT_INTENT_MUTATING: str
    EVENT_INTENT_NON_MUTATING_DEFER: str
    EVENT_INTENT_NON_MUTATING_READONLY: str

    def get_config_value(self, name: str, default: str = "") -> str: ...


@runtime_checkable
class AppExecutionRuntime(AppEventContextRuntime, Protocol):
    datetime: type[datetime]
    timezone: Any

    def write_output(self, name: str, value: str) -> None: ...
    def drain_touched_items(self) -> list[int]: ...
    def load_state(self, *, fail_on_unavailable: bool = False) -> dict: ...
    def save_state(self, state: dict) -> bool: ...
    def ensure_state_issue_lease_lock_fresh(self) -> bool: ...
    def acquire_state_issue_lease_lock(self) -> LeaseContext: ...
    def release_state_issue_lease_lock(self) -> bool: ...
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
    def sync_status_labels_for_items(self, state: dict, issue_numbers: Iterable[int]) -> bool: ...


@runtime_checkable
class GitHubApiContext(Protocol):
    """Minimal runtime surface required by github_api helpers."""

    LOCK_API_RETRY_LIMIT: int
    LOCK_RETRY_BASE_SECONDS: float
    REVIEWER_REQUEST_422_TEMPLATE: str
    AssignmentAttempt: type[AssignmentAttempt]
    GitHubApiResult: type[GitHubApiResult]
    logger: Logger
    rest_transport: RestTransport
    graphql_transport: GraphQLTransport

    def get_config_value(self, name: str, default: str = "") -> str: ...
    def get_github_token(self) -> str: ...
    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str: ...


@runtime_checkable
class GitHubTransportContext(GitHubApiContext, Protocol):
    """Compatibility transport surface expected by call sites."""

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
class StateStoreRuntimeContext(Protocol):
    """Minimal runtime surface required by state_store helpers."""

    ACTIVE_LEASE_CONTEXT: LeaseContext | None
    STATE_ISSUE_NUMBER: int
    STATE_READ_RETRY_LIMIT: int
    STATE_READ_RETRY_BASE_SECONDS: float
    LOCK_API_RETRY_LIMIT: int
    LOCK_RETRY_BASE_SECONDS: float
    GitHubApiResult: type[GitHubApiResult]
    logger: Logger
    sleeper: Sleeper
    jitter: JitterSource
    clock: Clock

    def get_config_value(self, name: str, default: str = "") -> str: ...
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
    def state_issue_number(self) -> int: ...
    def lock_api_retry_limit(self) -> int: ...
    def lock_retry_base_seconds(self) -> float: ...


@runtime_checkable
class StateStoreContext(StateStoreRuntimeContext, Protocol):
    """Compatibility state-store surface expected by current runtime."""

    def get_state_issue(self) -> dict | None: ...
    def get_state_issue_snapshot(self) -> StateIssueSnapshot | None: ...
    def conditional_patch_state_issue(self, body: str, etag: str | None = None) -> GitHubApiResult: ...


@runtime_checkable
class LeaseLockRuntimeContext(Protocol):
    """Minimal runtime surface required by lease_lock helpers."""

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
    logger: Logger
    sleeper: Sleeper
    jitter: JitterSource
    clock: Clock
    uuid_source: UuidSource
    time: Any

    def get_config_value(self, name: str, default: str = "") -> str: ...
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
    def build_lock_metadata(
        self,
        lock_token: str,
        lock_owner_run_id: str,
        lock_owner_workflow: str,
        lock_owner_job: str,
    ) -> dict: ...
    def lock_is_currently_valid(self, lock_meta: dict, now: datetime | None = None) -> bool: ...
    def lock_api_retry_limit(self) -> int: ...
    def lock_retry_base_seconds(self) -> float: ...
    def lock_lease_ttl_seconds(self) -> int: ...
    def lock_max_wait_seconds(self) -> int: ...
    def lock_renewal_window_seconds(self) -> int: ...
    def lock_ref_name(self) -> str: ...
    def lock_ref_bootstrap_branch(self) -> str: ...


@runtime_checkable
class LeaseLockContext(LeaseLockRuntimeContext, Protocol):
    """Compatibility lock surface expected by current runtime."""

    def get_lock_ref_snapshot(self) -> tuple[str, str, dict]: ...
    def create_lock_commit(self, parent_sha: str, tree_sha: str, lock_meta: dict) -> GitHubApiResult: ...
    def cas_update_lock_ref(self, new_sha: str) -> GitHubApiResult: ...
    def renew_state_issue_lease_lock(self, context: LeaseContext) -> bool: ...


@runtime_checkable
class SweeperContext(Protocol):
    LOCK_RETRY_BASE_SECONDS: float
    STATUS_PROJECTION_EPOCH: str
    TRANSITION_PERIOD_DAYS: int
    DEFERRED_DISCOVERY_OVERLAP_SECONDS: int
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS: int
    REVIEW_FRESHNESS_RUNBOOK_PATH: str
    GitHubApiResult: type[GitHubApiResult]
    artifact_download_transport: ArtifactDownloadTransport
    jitter: JitterSource
    logger: Logger

    def get_config_value(self, name: str, default: str = "") -> str: ...
    def get_github_token(self) -> str: ...
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
    def get_pull_request_reviews(self, issue_number: int) -> list[dict] | None: ...
    def get_issue_or_pr_snapshot(self, issue_number: int) -> dict | None: ...
    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict) -> HeadObservationRepairResult: ...
    def compute_reviewer_response_state(
        self,
        issue_number: int,
        review_data: dict,
        *,
        issue_snapshot: dict | None = None,
        pull_request: dict | None = None,
        reviews: list[dict] | None = None,
    ) -> dict[str, object]: ...


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
    def get_config_value(self, name: str, default: str = "") -> str: ...
    def set_config_value(self, name: str, value: Any) -> None: ...
    def write_output(self, name: str, value: str) -> None: ...
    def load_deferred_payload(self) -> dict: ...
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
    def handle_transition_notice(self, state: dict, issue_number: int, reviewer: str) -> bool: ...
    def handle_pass_command(self, state: dict, issue_number: int, comment_author: str, reason: str | None, request: AssignmentRequest | None = None): ...
    def handle_pass_until_command(
        self,
        state: dict,
        issue_number: int,
        comment_author: str,
        return_date: str,
        reason: str | None,
        request: AssignmentRequest | None = None,
    ): ...
    def handle_label_command(self, state: dict, issue_number: int, label_string: str, request: AssignmentRequest | None = None): ...
    def handle_sync_members_command(self, state: dict): ...
    def handle_queue_command(self, state: dict): ...
    def handle_commands_command(self): ...
    def handle_claim_command(self, state: dict, issue_number: int, comment_author: str, request: AssignmentRequest | None = None): ...
    def handle_release_command(self, state: dict, issue_number: int, comment_author: str, args=None, request: AssignmentRequest | None = None): ...
    def handle_rectify_command(self, state: dict, issue_number: int, comment_author: str): ...
    def handle_assign_command(self, state: dict, issue_number: int, username: str, request: AssignmentRequest | None = None): ...
    def handle_assign_from_queue_command(self, state: dict, issue_number: int, request: AssignmentRequest | None = None): ...
    def handle_accept_no_fls_changes_command(
        self,
        issue_number: int,
        comment_author: str,
        request: PrivilegedCommandRequest | None = None,
    ): ...
    def get_commands_help(self) -> str: ...
