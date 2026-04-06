"""Decode runtime/config inputs into typed reviewer-bot request objects."""

from __future__ import annotations

import json
from pathlib import Path

from .context import (
    AssignmentRequest,
    CommentEventRequest,
    EventContext,
    EventInputsContext,
    IssueLifecycleRequest,
    LabelEventRequest,
    ManualDispatchRequest,
    PrCommentTrustContext,
    PrivilegedCommandRequest,
    PullRequestSyncRequest,
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


def get_target_repo_root(bot: EventInputsContext) -> Path | None:
    configured = bot.get_config_value("REVIEWER_BOT_TARGET_REPO_ROOT", "").strip()
    if not configured:
        return None
    return Path(configured)


def build_event_context(bot: EventInputsContext) -> EventContext:
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
        workflow_run_event=bot.get_config_value("WORKFLOW_RUN_EVENT").strip() or None,
        workflow_run_event_action=bot.get_config_value("WORKFLOW_RUN_EVENT_ACTION").strip() or None,
        workflow_run_head_sha=bot.get_config_value("WORKFLOW_RUN_HEAD_SHA").strip() or None,
        workflow_run_reconcile_pr_number=_parse_optional_int(bot.get_config_value("WORKFLOW_RUN_RECONCILE_PR_NUMBER")),
        workflow_run_reconcile_head_sha=bot.get_config_value("WORKFLOW_RUN_RECONCILE_HEAD_SHA").strip() or None,
        workflow_run_id=_parse_optional_int(bot.get_config_value("WORKFLOW_RUN_ID")),
        workflow_name=bot.get_config_value("WORKFLOW_NAME").strip() or None,
        workflow_job_name=bot.get_config_value("WORKFLOW_JOB_NAME").strip() or None,
        manual_action=bot.get_config_value("MANUAL_ACTION").strip() or None,
    )


def build_comment_event_request(bot: EventInputsContext, *, issue_number: int | None = None) -> CommentEventRequest:
    resolved_issue_number = issue_number if issue_number is not None else (_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0)
    return CommentEventRequest(
        issue_number=resolved_issue_number,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        issue_state=bot.get_config_value("ISSUE_STATE").strip().lower(),
        issue_author=bot.get_config_value("ISSUE_AUTHOR"),
        comment_id=_parse_optional_int(bot.get_config_value("COMMENT_ID")) or 0,
        comment_author=bot.get_config_value("COMMENT_AUTHOR"),
        comment_author_id=_parse_optional_int(bot.get_config_value("COMMENT_AUTHOR_ID")) or 0,
        comment_body=bot.get_config_value("COMMENT_BODY"),
        comment_created_at=bot.get_config_value("COMMENT_CREATED_AT"),
        comment_source_event_key=bot.get_config_value("COMMENT_SOURCE_EVENT_KEY").strip(),
        comment_user_type=bot.get_config_value("COMMENT_USER_TYPE").strip(),
        comment_sender_type=bot.get_config_value("COMMENT_SENDER_TYPE").strip(),
        comment_installation_id=bot.get_config_value("COMMENT_INSTALLATION_ID").strip(),
        comment_performed_via_github_app=bool(_parse_optional_bool(bot.get_config_value("COMMENT_PERFORMED_VIA_GITHUB_APP"))),
    )


def build_pr_comment_trust_context(bot: EventInputsContext) -> PrCommentTrustContext:
    github_run_id = _parse_optional_int(bot.get_config_value("GITHUB_RUN_ID")) or 0
    github_run_attempt = _parse_optional_int(bot.get_config_value("GITHUB_RUN_ATTEMPT")) or 0
    return PrCommentTrustContext(
        github_repository=bot.get_config_value("GITHUB_REPOSITORY"),
        comment_author_association=bot.get_config_value("COMMENT_AUTHOR_ASSOCIATION").strip(),
        current_workflow_file=bot.get_config_value("CURRENT_WORKFLOW_FILE").strip(),
        github_ref=bot.get_config_value("GITHUB_REF").strip(),
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
    target_repo_root = bot.get_config_value("REVIEWER_BOT_TARGET_REPO_ROOT").strip()
    workflow_run_reconcile_pr_number = bot.get_config_value("WORKFLOW_RUN_RECONCILE_PR_NUMBER").strip()
    return PrivilegedCommandRequest(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS", "[]")),
        target_repo_root=target_repo_root,
        workflow_run_reconcile_pr_number=_parse_optional_int(workflow_run_reconcile_pr_number),
        workflow_run_reconcile_head_sha=bot.get_config_value("WORKFLOW_RUN_RECONCILE_HEAD_SHA").strip(),
        workflow_run_head_sha=bot.get_config_value("WORKFLOW_RUN_HEAD_SHA").strip(),
    )


def build_manual_dispatch_request(bot: EventInputsContext) -> ManualDispatchRequest:
    return ManualDispatchRequest(
        action=bot.get_config_value("MANUAL_ACTION").strip(),
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")),
        privileged_source_event_key=bot.get_config_value("PRIVILEGED_SOURCE_EVENT_KEY").strip(),
    )


def build_issue_lifecycle_request(bot: EventInputsContext) -> IssueLifecycleRequest:
    return IssueLifecycleRequest(
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        issue_labels=_parse_labels(bot.get_config_value("ISSUE_LABELS")),
        issue_author=bot.get_config_value("ISSUE_AUTHOR").strip(),
        sender_login=bot.get_config_value("SENDER_LOGIN").strip(),
        updated_at=bot.get_config_value("ISSUE_UPDATED_AT").strip(),
        issue_title=bot.get_config_value("ISSUE_TITLE"),
        issue_body=bot.get_config_value("ISSUE_BODY"),
        previous_title=bot.get_config_value("ISSUE_CHANGES_TITLE_FROM"),
        previous_body=bot.get_config_value("ISSUE_CHANGES_BODY_FROM"),
        pr_head_sha=bot.get_config_value("PR_HEAD_SHA").strip(),
        event_created_at=bot.get_config_value("EVENT_CREATED_AT").strip(),
    )


def build_label_event_request(bot: EventInputsContext) -> LabelEventRequest:
    return LabelEventRequest(
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        is_pull_request=bool(_parse_optional_bool(bot.get_config_value("IS_PULL_REQUEST"))),
        label_name=bot.get_config_value("LABEL_NAME"),
    )


def build_pull_request_sync_request(bot: EventInputsContext) -> PullRequestSyncRequest:
    return PullRequestSyncRequest(
        issue_number=_parse_optional_int(bot.get_config_value("ISSUE_NUMBER")) or 0,
        head_sha=bot.get_config_value("PR_HEAD_SHA").strip(),
        event_created_at=bot.get_config_value("EVENT_CREATED_AT").strip(),
    )
