"""Decode env/config inputs into typed reviewer-bot request objects."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .context import (
    AppEventContextRuntime,
    AssignmentRequest,
    CommentEventRequest,
    EventContext,
    PrCommentTrustContext,
    PrivilegedCommandRequest,
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


def parse_issue_labels_env() -> list[str]:
    return list(_parse_labels(os.environ.get("ISSUE_LABELS", "[]")))


def get_target_repo_root_from_env() -> Path | None:
    configured = os.environ.get("REVIEWER_BOT_TARGET_REPO_ROOT", "").strip()
    if not configured:
        return None
    return Path(configured)


def build_event_context(bot: AppEventContextRuntime) -> EventContext:
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


def build_comment_event_request(*, issue_number: int | None = None) -> CommentEventRequest:
    return CommentEventRequest(
        issue_number=issue_number if issue_number is not None else int(os.environ.get("ISSUE_NUMBER", "0") or 0),
        is_pull_request=os.environ.get("IS_PULL_REQUEST", "false").lower() == "true",
        issue_state=os.environ.get("ISSUE_STATE", "").strip().lower(),
        issue_author=os.environ.get("ISSUE_AUTHOR", ""),
        comment_id=int(os.environ.get("COMMENT_ID", "0") or 0),
        comment_author=os.environ.get("COMMENT_AUTHOR", ""),
        comment_author_id=int(os.environ.get("COMMENT_AUTHOR_ID", "0") or 0),
        comment_body=os.environ.get("COMMENT_BODY", ""),
        comment_created_at=os.environ.get("COMMENT_CREATED_AT", ""),
        comment_source_event_key=os.environ.get("COMMENT_SOURCE_EVENT_KEY", "").strip(),
        comment_user_type=os.environ.get("COMMENT_USER_TYPE", "").strip(),
        comment_sender_type=os.environ.get("COMMENT_SENDER_TYPE", "").strip(),
        comment_installation_id=os.environ.get("COMMENT_INSTALLATION_ID", "").strip(),
        comment_performed_via_github_app=os.environ.get("COMMENT_PERFORMED_VIA_GITHUB_APP", "").strip().lower() == "true",
    )


def build_pr_comment_trust_context() -> PrCommentTrustContext:
    return PrCommentTrustContext(
        github_repository=os.environ.get("GITHUB_REPOSITORY", ""),
        comment_author_association=os.environ.get("COMMENT_AUTHOR_ASSOCIATION", "").strip(),
        current_workflow_file=os.environ.get("CURRENT_WORKFLOW_FILE", "").strip(),
        github_ref=os.environ.get("GITHUB_REF", "").strip(),
        github_run_id=int(os.environ.get("GITHUB_RUN_ID", "0") or 0),
        github_run_attempt=int(os.environ.get("GITHUB_RUN_ATTEMPT", "0") or 0),
    )


def build_assignment_request(*, issue_number: int) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=issue_number,
        issue_author=os.environ.get("ISSUE_AUTHOR", ""),
        is_pull_request=os.environ.get("IS_PULL_REQUEST", "false").lower() == "true",
        issue_labels=_parse_labels(os.environ.get("ISSUE_LABELS", "[]")),
        repo_owner=os.environ.get("REPO_OWNER", ""),
        repo_name=os.environ.get("REPO_NAME", ""),
    )


def build_privileged_command_request(*, issue_number: int, actor: str = "", command_name: str = "") -> PrivilegedCommandRequest:
    target_repo_root = os.environ.get("REVIEWER_BOT_TARGET_REPO_ROOT", "").strip()
    workflow_run_reconcile_pr_number = os.environ.get("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "").strip()
    return PrivilegedCommandRequest(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
        is_pull_request=os.environ.get("IS_PULL_REQUEST", "false").lower() == "true",
        issue_labels=_parse_labels(os.environ.get("ISSUE_LABELS", "[]")),
        target_repo_root=target_repo_root,
        workflow_run_reconcile_pr_number=int(workflow_run_reconcile_pr_number) if workflow_run_reconcile_pr_number else None,
        workflow_run_reconcile_head_sha=os.environ.get("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "").strip(),
        workflow_run_head_sha=os.environ.get("WORKFLOW_RUN_HEAD_SHA", "").strip(),
    )
