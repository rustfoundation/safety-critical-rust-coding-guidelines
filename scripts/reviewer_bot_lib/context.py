"""Request-boundary dataclasses for reviewer-bot modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.reviewer_bot_core.comment_routing_policy import PrCommentRouterOutcome


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
    workflow_kind: str | None = None
    workflow_run_triggering_conclusion: str | None = None
    workflow_artifact_contract: str | None = None
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
    issue_state: str
    issue_author: str
    issue_labels: tuple[str, ...]
    comment_id: int
    comment_author: str
    comment_author_id: int
    comment_body: str
    comment_created_at: str
    comment_source_event_key: str
    comment_user_type: str
    comment_sender_type: str
    comment_installation_id: str | None
    comment_performed_via_github_app: bool


@dataclass(frozen=True)
class PrCommentAdmission:
    route_outcome: PrCommentRouterOutcome
    declared_trust_class: str
    github_repository: str
    pr_head_full_name: str
    pr_author: str
    issue_state: str
    issue_labels: tuple[str, ...]
    comment_author_id: int
    github_run_id: int
    github_run_attempt: int


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
