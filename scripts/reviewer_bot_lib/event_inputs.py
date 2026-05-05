"""Decode runtime/config inputs into typed reviewer-bot request objects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.reviewer_bot_core.comment_routing_policy import PrCommentRouterOutcome

from .context import (
    AssignmentRequest,
    CommentEventRequest,
    EventContext,
    IssueLifecycleRequest,
    LabelEventRequest,
    ManualDispatchRequest,
    PrCommentAdmission,
    PrivilegedCommandRequest,
    PullRequestSyncRequest,
)
from .runtime_protocols import EventInputsContext


class InvalidEventInput(RuntimeError):
    def __init__(self, builder: str, problems: tuple[str, ...]):
        self.builder = builder
        self.problems = problems
        super().__init__(f"{builder}: {'; '.join(problems)}")


@dataclass(frozen=True)
class LifecycleEventTimestampEvidence:
    event_name: str
    event_action: str
    source_created_at: str | None
    source_updated_at: str | None
    source_closed_at: str | None
    selected_timestamp: str | None
    selection_kind: str
    selection_reason: str
    is_authoritative: bool

    def to_output(self) -> dict[str, object]:
        return {
            "event_name": self.event_name,
            "event_action": self.event_action,
            "source_created_at": self.source_created_at,
            "source_updated_at": self.source_updated_at,
            "source_closed_at": self.source_closed_at,
            "selected_timestamp": self.selected_timestamp,
            "selection_kind": self.selection_kind,
            "selection_reason": self.selection_reason,
            "is_authoritative": self.is_authoritative,
        }


def derive_lifecycle_event_timestamp(
    *,
    event_name: str,
    event_action: str,
    source_created_at: str | None,
    source_updated_at: str | None,
    source_closed_at: str | None,
) -> LifecycleEventTimestampEvidence:
    selected = None
    kind = "blocked"
    reason = "unsupported_action"
    if event_action == "opened":
        selected = source_created_at
        kind = "created_at"
        reason = "opened_uses_created_at"
    elif event_action == "closed":
        selected = source_closed_at
        kind = "closed_at"
        reason = "closed_uses_closed_at"
    elif event_action in {"edited", "assigned", "unassigned", "labeled", "unlabeled", "reopened", "synchronize"}:
        selected = source_updated_at
        kind = "explicit_action_proxy"
        reason = f"{event_action}_uses_updated_at_proxy"
    authoritative = isinstance(selected, str) and selected.strip() and _is_parseable_iso8601(selected)
    return LifecycleEventTimestampEvidence(
        event_name=event_name,
        event_action=event_action,
        source_created_at=source_created_at,
        source_updated_at=source_updated_at,
        source_closed_at=source_closed_at,
        selected_timestamp=selected if authoritative else None,
        selection_kind=kind if authoritative else "blocked",
        selection_reason=reason if authoritative else "invalid_or_missing_timestamp",
        is_authoritative=bool(authoritative),
    )


def _parse_optional_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_optional_bool(value: str) -> bool | None:
    value = value.strip().lower()
    if not value:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _parse_required_bool(value: str) -> bool | None:
    return _parse_optional_bool(value)


def _parse_labels(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(label) for label in payload)


def parse_issue_labels(bot: EventInputsContext) -> list[str]:
    return list(_parse_labels(bot.get_config_value("ISSUE_LABELS", "[]")))


def _is_parseable_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _raise_invalid(builder: str, problems: list[str]) -> None:
    raise InvalidEventInput(builder, tuple(problems))


def _parse_required_labels(builder: str, raw_value: str, problems: list[str]) -> tuple[str, ...]:
    value = raw_value.strip()
    if not value:
        problems.append("ISSUE_LABELS must be present")
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        problems.append("ISSUE_LABELS must be valid JSON")
        return ()
    if not isinstance(payload, list):
        problems.append("ISSUE_LABELS must decode to a JSON list")
        return ()
    return tuple(str(label) for label in payload)


def _derive_comment_source_event_key(bot: EventInputsContext, comment_id: int) -> str | None:
    event_name = bot.get_config_value("EVENT_NAME").strip()
    if event_name == "issue_comment":
        return f"issue_comment:{comment_id}"
    if event_name == "pull_request_review_comment":
        return f"pull_request_review_comment:{comment_id}"
    return None


def _parse_route_outcome(value: str) -> PrCommentRouterOutcome | None:
    normalized = value.strip().lower()
    if not normalized:
        return None
    try:
        return PrCommentRouterOutcome(normalized)
    except ValueError:
        return None


def _lifecycle_timestamp_config_name(*, action: str, is_pull_request: bool) -> str | None:
    if is_pull_request:
        if action == "opened":
            return "PR_CREATED_AT"
        if action == "closed":
            return "PR_CLOSED_AT"
        if action in {"labeled", "unlabeled", "reopened", "synchronize"}:
            return "PR_UPDATED_AT"
        return None
    if action == "opened":
        return "ISSUE_CREATED_AT"
    if action == "closed":
        return "ISSUE_CLOSED_AT"
    if action in {"edited", "assigned", "unassigned", "labeled", "unlabeled", "reopened"}:
        return "ISSUE_UPDATED_AT"
    return None


def _derive_lifecycle_event_created_at(bot: EventInputsContext, *, action: str, is_pull_request: bool) -> str:
    event_name = "pull_request_target" if is_pull_request else "issues"
    evidence = derive_lifecycle_event_timestamp(
        event_name=event_name,
        event_action=action,
        source_created_at=bot.get_config_value("PR_CREATED_AT" if is_pull_request else "ISSUE_CREATED_AT").strip() or None,
        source_updated_at=bot.get_config_value("PR_UPDATED_AT" if is_pull_request else "ISSUE_UPDATED_AT").strip() or None,
        source_closed_at=bot.get_config_value("PR_CLOSED_AT" if is_pull_request else "ISSUE_CLOSED_AT").strip() or None,
    )
    if evidence.selected_timestamp:
        return evidence.selected_timestamp
    config_name = _lifecycle_timestamp_config_name(action=action, is_pull_request=is_pull_request)
    return bot.get_config_value(config_name).strip() if config_name else ""


def _validate_lifecycle_event_created_at(
    builder: str,
    *,
    action: str,
    is_pull_request: bool,
    event_created_at: str,
) -> None:
    config_name = _lifecycle_timestamp_config_name(action=action, is_pull_request=is_pull_request)
    if config_name is None:
        return
    problems: list[str] = []
    if not event_created_at:
        problems.append(f"{config_name} must be non-empty for {action}")
    elif not _is_parseable_iso8601(event_created_at):
        problems.append(f"{config_name} must be parseable ISO-8601 for {action}")
    if problems:
        _raise_invalid(builder, problems)


def _read_workflow_run_name(bot: EventInputsContext) -> str:
    event_path = bot.get_config_value("GITHUB_EVENT_PATH").strip()
    if not event_path:
        return ""
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    workflow_run = payload.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return ""
    name = workflow_run.get("name")
    return name.strip() if isinstance(name, str) else ""


def build_event_context(bot: EventInputsContext) -> EventContext:
    workflow_kind = bot.get_config_value("REVIEWER_BOT_WORKFLOW_KIND").strip() or None
    workflow_artifact_contract = None
    if bot.get_config_value("EVENT_NAME").strip() == "workflow_run":
        workflow_artifact_contract = (
            "artifact_optional_router"
            if _read_workflow_run_name(bot) == "Reviewer Bot PR Comment Router"
            else "artifact_required"
        )
    return EventContext(
        event_name=bot.get_config_value("EVENT_NAME").strip(),
        event_action=bot.get_config_value("EVENT_ACTION").strip(),
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")),
        is_pull_request=_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST")),
        issue_author=bot.get_config_value("ISSUE_AUTHOR").strip() or None,
        issue_state=bot.get_config_value("ISSUE_STATE").strip() or None,
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS")),
        comment_id=_parse_optional_int(bot.get_config_value("COMMENT_ID")),
        comment_author=bot.get_config_value("COMMENT_AUTHOR").strip() or None,
        comment_body=bot.get_config_value("COMMENT_BODY") or None,
        comment_source_event_key=bot.get_config_value("COMMENT_SOURCE_EVENT_KEY").strip() or None,
        pr_is_cross_repository=_parse_optional_bool(bot.get_config_value("PR_IS_CROSS_REPOSITORY")),
        review_author=bot.get_config_value("REVIEW_AUTHOR").strip() or None,
        review_state=bot.get_config_value("REVIEW_STATE").strip() or None,
        workflow_kind=workflow_kind,
        workflow_run_triggering_conclusion=bot.get_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION").strip() or None,
        workflow_artifact_contract=workflow_artifact_contract,
        manual_action=bot.get_config_value("MANUAL_ACTION").strip() or None,
    )


def build_comment_event_request(bot: EventInputsContext, *, issue_number: int | None = None) -> CommentEventRequest:
    builder = "build_comment_event_request"
    problems: list[str] = []
    resolved_issue_number = issue_number if issue_number is not None else _parse_optional_int(bot.get_config_value("ISSUE_NUMBER"))
    if resolved_issue_number is None or resolved_issue_number <= 0:
        problems.append("ISSUE_NUMBER must be a positive integer")
    is_pull_request = _parse_required_bool(bot.get_config_value("IS_PULL_REQUEST"))
    if is_pull_request is None:
        problems.append("IS_PULL_REQUEST must be parseable as a boolean")
    issue_state = bot.get_config_value("ISSUE_STATE").strip().lower()
    if not issue_state:
        problems.append("ISSUE_STATE must be non-empty")
    issue_author = bot.get_config_value("ISSUE_AUTHOR").strip()
    if not issue_author:
        problems.append("ISSUE_AUTHOR must be non-empty")
    issue_labels = _parse_required_labels(builder, bot.get_config_value("ISSUE_LABELS", "[]"), problems)
    comment_id = _parse_optional_int(bot.get_config_value("COMMENT_ID"))
    if comment_id is None or comment_id <= 0:
        problems.append("COMMENT_ID must be a positive integer")
        comment_id = 0
    comment_author = bot.get_config_value("COMMENT_AUTHOR").strip()
    if not comment_author:
        problems.append("COMMENT_AUTHOR must be non-empty")
    comment_author_id = _parse_optional_int(bot.get_config_value("COMMENT_AUTHOR_ID"))
    if comment_author_id is None or comment_author_id <= 0:
        problems.append("COMMENT_AUTHOR_ID must be a positive integer")
        comment_author_id = 0
    comment_body = bot.get_config_value("COMMENT_BODY")
    comment_created_at = bot.get_config_value("COMMENT_CREATED_AT").strip()
    if not comment_created_at:
        problems.append("COMMENT_CREATED_AT must be non-empty")
    elif not _is_parseable_iso8601(comment_created_at):
        problems.append("COMMENT_CREATED_AT must be parseable ISO-8601")
    comment_source_event_key = bot.get_config_value("COMMENT_SOURCE_EVENT_KEY").strip()
    if not comment_source_event_key and comment_id > 0:
        comment_source_event_key = _derive_comment_source_event_key(bot, comment_id) or ""
    if not comment_source_event_key:
        problems.append("COMMENT_SOURCE_EVENT_KEY must be non-empty")
    comment_user_type = bot.get_config_value("COMMENT_USER_TYPE").strip()
    if not comment_user_type:
        problems.append("COMMENT_USER_TYPE must be non-empty")
    comment_author_association = bot.get_config_value("COMMENT_AUTHOR_ASSOCIATION").strip().upper()
    if is_pull_request is True and not comment_author_association:
        problems.append("COMMENT_AUTHOR_ASSOCIATION must be non-empty for PR comments")
    comment_sender_type = bot.get_config_value("COMMENT_SENDER_TYPE").strip()
    if not comment_sender_type:
        problems.append("COMMENT_SENDER_TYPE must be non-empty")
    comment_installation_id = bot.get_config_value("COMMENT_INSTALLATION_ID").strip() or None
    comment_performed_via_github_app = _parse_required_bool(bot.get_config_value("COMMENT_PERFORMED_VIA_GITHUB_APP"))
    if comment_performed_via_github_app is None:
        problems.append("COMMENT_PERFORMED_VIA_GITHUB_APP must be parseable as a boolean")
    if problems:
        _raise_invalid(builder, problems)
    return CommentEventRequest(
        issue_number=resolved_issue_number,
        is_pull_request=is_pull_request,
        issue_state=issue_state,
        issue_author=issue_author,
        issue_labels=issue_labels,
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
        comment_author_association=comment_author_association,
        comment_source_kind="issue_comment",
        reviewed_head_sha=None,
    )


def build_pr_comment_admission(
    bot: EventInputsContext,
    request: CommentEventRequest | None = None,
) -> PrCommentAdmission | None:
    builder = "build_pr_comment_admission"
    route_outcome = _parse_route_outcome(bot.get_config_value("REVIEWER_BOT_ROUTE_OUTCOME"))
    if route_outcome in {None, PrCommentRouterOutcome.DEFERRED_RECONCILE, PrCommentRouterOutcome.SAFE_NOOP}:
        return None
    problems: list[str] = []
    if route_outcome is not PrCommentRouterOutcome.TRUSTED_DIRECT:
        problems.append("REVIEWER_BOT_ROUTE_OUTCOME must be a retained PR comment router outcome")
    declared_trust_class = bot.get_config_value("REVIEWER_BOT_TRUST_CLASS").strip()
    if declared_trust_class != "pr_trusted_direct":
        problems.append("REVIEWER_BOT_TRUST_CLASS must equal pr_trusted_direct")
    github_repository = bot.get_config_value("GITHUB_REPOSITORY").strip()
    if not github_repository:
        problems.append("GITHUB_REPOSITORY must be non-empty")
    pr_head_full_name = bot.get_config_value("PR_HEAD_FULL_NAME").strip()
    if not pr_head_full_name:
        problems.append("PR_HEAD_FULL_NAME must be non-empty")
    pr_author = bot.get_config_value("PR_AUTHOR").strip()
    if not pr_author:
        problems.append("PR_AUTHOR must be non-empty")
    issue_state = bot.get_config_value("ISSUE_STATE").strip().lower()
    if not issue_state:
        problems.append("ISSUE_STATE must be non-empty")
    issue_labels = _parse_required_labels(builder, bot.get_config_value("ISSUE_LABELS", "[]"), problems)
    comment_author_id = _parse_optional_int(bot.get_config_value("COMMENT_AUTHOR_ID"))
    if comment_author_id is None or comment_author_id <= 0:
        problems.append("COMMENT_AUTHOR_ID must be a positive integer")
        comment_author_id = 0
    github_run_id = _parse_optional_int(bot.get_config_value("GITHUB_RUN_ID"))
    if github_run_id is None or github_run_id <= 0:
        problems.append("GITHUB_RUN_ID must be a positive integer")
        github_run_id = 0
    github_run_attempt = _parse_optional_int(bot.get_config_value("GITHUB_RUN_ATTEMPT"))
    if github_run_attempt is None or github_run_attempt <= 0:
        problems.append("GITHUB_RUN_ATTEMPT must be a positive integer")
        github_run_attempt = 0
    if request is not None:
        if request.issue_state != issue_state:
            problems.append("ISSUE_STATE must match comment request admission boundary copy")
        if request.issue_labels != issue_labels:
            problems.append("ISSUE_LABELS must match comment request admission boundary copy")
        if request.comment_author_id != comment_author_id:
            problems.append("COMMENT_AUTHOR_ID must match comment request admission boundary copy")
    if problems:
        _raise_invalid(builder, problems)
    return PrCommentAdmission(
        route_outcome=route_outcome,
        declared_trust_class=declared_trust_class,
        github_repository=github_repository,
        pr_head_full_name=pr_head_full_name,
        pr_author=pr_author,
        issue_state=issue_state,
        issue_labels=issue_labels,
        comment_author_id=comment_author_id,
        github_run_id=github_run_id,
        github_run_attempt=github_run_attempt,
    )


def build_assignment_request(bot: EventInputsContext, *, issue_number: int) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=issue_number,
        issue_author=bot.get_config_value("ISSUE_AUTHOR"),
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS", "[]")),
        repo_owner=bot.get_config_value("REPO_OWNER"),
        repo_name=bot.get_config_value("REPO_NAME"),
    )


def build_privileged_command_request(
    bot: EventInputsContext,
    *,
    issue_number: int,
    actor: str = "",
    command_name: str = "",
) -> PrivilegedCommandRequest:
    return PrivilegedCommandRequest(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS", "[]")),
    )


def build_pending_privileged_command_request(record) -> PrivilegedCommandRequest:
    return PrivilegedCommandRequest(
        issue_number=record.issue_number,
        actor=record.actor,
        command_name=record.command_name,
        is_pull_request=False,
        issue_labels=record.target_labels_snapshot,
    )


def build_manual_dispatch_request(bot: EventInputsContext) -> ManualDispatchRequest:
    return ManualDispatchRequest(
        action=bot.get_config_value("MANUAL_ACTION").strip(),
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")),
        validation_nonce=bot.get_config_value("VALIDATION_NONCE").strip(),
        privileged_source_event_key=bot.get_config_value("PRIVILEGED_SOURCE_EVENT_KEY").strip(),
    )


def build_issue_lifecycle_request(bot: EventInputsContext) -> IssueLifecycleRequest:
    builder = "build_issue_lifecycle_request"
    event_action = bot.get_config_value("EVENT_ACTION").strip()
    is_pull_request = bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST")))
    event_created_at = _derive_lifecycle_event_created_at(
        bot,
        action=event_action,
        is_pull_request=is_pull_request,
    )
    _validate_lifecycle_event_created_at(
        builder,
        action=event_action,
        is_pull_request=is_pull_request,
        event_created_at=event_created_at,
    )
    return IssueLifecycleRequest(
        event_action=event_action,
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        is_pull_request=is_pull_request,
        issue_state=bot.get_config_value("ISSUE_STATE").strip(),
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS")),
        label_name=bot.get_config_value("LABEL_NAME").strip(),
        issue_author=bot.get_config_value("ISSUE_AUTHOR").strip(),
        sender_login=bot.get_config_value("SENDER_LOGIN").strip(),
        updated_at=bot.get_config_value("ISSUE_UPDATED_AT").strip(),
        issue_title=bot.get_config_value("ISSUE_TITLE"),
        issue_body=bot.get_config_value("ISSUE_BODY"),
        previous_title=bot.get_config_value("ISSUE_CHANGES_TITLE_FROM"),
        previous_body=bot.get_config_value("ISSUE_CHANGES_BODY_FROM"),
        pr_head_sha=bot.get_config_value("PR_HEAD_SHA").strip(),
        event_created_at=event_created_at,
    )


def build_label_event_request(bot: EventInputsContext) -> LabelEventRequest:
    return LabelEventRequest(
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        label_name=bot.get_config_value("LABEL_NAME"),
    )


def build_pull_request_sync_request(bot: EventInputsContext) -> PullRequestSyncRequest:
    event_created_at = _derive_lifecycle_event_created_at(bot, action="synchronize", is_pull_request=True)
    _validate_lifecycle_event_created_at(
        "build_pull_request_sync_request",
        action="synchronize",
        is_pull_request=True,
        event_created_at=event_created_at,
    )
    return PullRequestSyncRequest(
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        head_sha=bot.get_config_value("PR_HEAD_SHA").strip(),
        event_created_at=event_created_at,
    )


def build_replay_comment_event_request(
    payload,
    *,
    live_comment=None,
    live_pr=None,
    comment_body: str | None = None,
) -> CommentEventRequest:
    if not hasattr(payload, "identity") or not hasattr(payload, "comment_id"):
        raise InvalidEventInput("build_replay_comment_event_request", ("typed deferred comment payload required",))
    if not hasattr(payload, "issue_state") or not hasattr(payload, "issue_author") or not hasattr(payload, "issue_labels"):
        raise InvalidEventInput("build_replay_comment_event_request", ("typed deferred comment payload required",))
    resolved_body = payload.comment_body if comment_body is None else comment_body
    comment_sender_type = (
        live_comment.comment_sender_type
        if live_comment is not None and live_comment.comment_sender_type_available
        else payload.comment_sender_type
    )
    comment_installation_id = (
        live_comment.comment_installation_id
        if live_comment is not None and live_comment.comment_installation_id_available
        else payload.comment_installation_id
    )
    comment_performed_via_github_app = (
        live_comment.comment_performed_via_github_app
        if live_comment is not None and live_comment.comment_performed_via_github_app_available
        else payload.comment_performed_via_github_app
    )
    issue_author = payload.issue_author
    if live_pr is not None and not issue_author.strip():
        issue_author = live_pr.issue_author
    issue_labels = payload.issue_labels
    if live_pr is not None and not issue_labels:
        issue_labels = live_pr.issue_labels
    payload_kind = getattr(payload.identity.payload_kind, "value", str(payload.identity.payload_kind))
    source_kind = "pull_request_review_comment" if payload_kind == "deferred_review_comment" else "issue_comment"
    return CommentEventRequest(
        issue_number=payload.identity.pr_number,
        is_pull_request=True,
        issue_state=payload.issue_state,
        issue_author=issue_author,
        issue_labels=issue_labels,
        comment_id=payload.comment_id,
        comment_author=(live_comment.comment_author if live_comment is not None else payload.comment_author),
        comment_author_id=payload.comment_author_id,
        comment_body=resolved_body,
        comment_created_at=payload.comment_created_at,
        comment_source_event_key=payload.identity.source_event_key,
        comment_user_type=(live_comment.comment_user_type if live_comment is not None else payload.comment_user_type),
        comment_sender_type=comment_sender_type,
        comment_installation_id=comment_installation_id,
        comment_performed_via_github_app=comment_performed_via_github_app,
        comment_source_kind=source_kind,
        reviewed_head_sha=payload.source_commit_id if source_kind == "pull_request_review_comment" else None,
    )
