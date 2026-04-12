"""Trust-routing and comment-payload classification owner."""

from __future__ import annotations

import re
from enum import StrEnum

from scripts.reviewer_bot_lib.context import PrCommentAdmission


class PrCommentRouterOutcome(StrEnum):
    TRUSTED_DIRECT = "trusted_direct"
    DEFERRED_RECONCILE = "deferred_reconcile"
    SAFE_NOOP = "safe_noop"


class ActorClass(StrEnum):
    BOT_ACCOUNT = "bot_account"
    GITHUB_APP_OR_OTHER_AUTOMATION = "github_app_or_other_automation"
    REPO_USER_PRINCIPAL = "repo_user_principal"
    UNKNOWN_ACTOR = "unknown_actor"


class ProcessingTarget(StrEnum):
    ISSUE_DIRECT = "issue_direct"
    PR_TRUSTED_DIRECT = "pr_trusted_direct"


class ObserverCommentClassification(StrEnum):
    EMPTY_OR_WHITESPACE = "empty_or_whitespace"
    PLAIN_TEXT = "plain_text"
    COMMAND_ONLY = "command_only"
    COMMAND_PLUS_TEXT = "command_plus_text"


class DirectCommentClassification(StrEnum):
    NOOP = "noop"
    FRESHNESS_ONLY = "freshness_only"
    COMMAND_ONLY = "command_only"
    BOTH = "both"


def classify_issue_comment_actor(request) -> ActorClass:
    comment_user_type = request.comment_user_type
    comment_author = request.comment_author.strip()
    sender_type = request.comment_sender_type
    installation_id = request.comment_installation_id
    via_github_app = request.comment_performed_via_github_app
    if comment_user_type == "Bot" or comment_author.endswith("[bot]"):
        return ActorClass.BOT_ACCOUNT
    if installation_id or via_github_app or (sender_type and sender_type not in {"User", "Bot"}):
        return ActorClass.GITHUB_APP_OR_OTHER_AUTOMATION
    if comment_user_type == "User" and comment_author and not comment_author.endswith("[bot]") and not installation_id and not via_github_app:
        return ActorClass.REPO_USER_PRINCIPAL
    return ActorClass.UNKNOWN_ACTOR


def comment_line_is_command(bot_mention: str, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    pattern = rf"^{re.escape(bot_mention)}\s+/[A-Za-z0-9?_-]+(?:\s+.*)?$"
    return re.match(pattern, stripped) is not None


def classify_comment_payload(bot_mention: str, normalized_body: str, parsed_command) -> dict:
    if not normalized_body:
        return {
            "comment_class": ObserverCommentClassification.EMPTY_OR_WHITESPACE,
            "has_non_command_text": False,
            "command_count": 0,
            "command": None,
            "args": [],
            "normalized_body": normalized_body,
        }
    lines = [line for line in normalized_body.splitlines() if line.strip()]
    command_lines = [line for line in lines if comment_line_is_command(bot_mention, line)]
    non_command_lines = [line for line in lines if not comment_line_is_command(bot_mention, line)]
    command = None
    args: list[str] = []
    if parsed_command:
        command, args = parsed_command
    if command_lines and not non_command_lines:
        comment_class = ObserverCommentClassification.COMMAND_ONLY
    elif command_lines and non_command_lines:
        comment_class = ObserverCommentClassification.COMMAND_PLUS_TEXT
    else:
        comment_class = ObserverCommentClassification.PLAIN_TEXT
    return {
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "command_count": len(command_lines),
        "command": command,
        "args": args,
        "normalized_body": normalized_body,
    }


def classify_pr_comment_processing_target(
    request,
    pr_admission: PrCommentAdmission,
    *,
    actor_class: ActorClass,
    is_self_comment: bool,
) -> ProcessingTarget | PrCommentRouterOutcome:
    if actor_class in {ActorClass.BOT_ACCOUNT, ActorClass.GITHUB_APP_OR_OTHER_AUTOMATION} or is_self_comment:
        return PrCommentRouterOutcome.SAFE_NOOP
    if pr_admission.route_outcome is not PrCommentRouterOutcome.TRUSTED_DIRECT:
        return pr_admission.route_outcome
    if pr_admission.pr_head_full_name != pr_admission.github_repository:
        return PrCommentRouterOutcome.DEFERRED_RECONCILE
    if pr_admission.pr_author == "dependabot[bot]":
        return PrCommentRouterOutcome.DEFERRED_RECONCILE
    if actor_class is ActorClass.REPO_USER_PRINCIPAL and pr_admission.declared_trust_class == "pr_trusted_direct":
        return ProcessingTarget.PR_TRUSTED_DIRECT
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def route_issue_comment_trust(request, pr_admission: PrCommentAdmission | None, *, processing_target=None):
    if not request.is_pull_request:
        return ProcessingTarget.ISSUE_DIRECT
    target = processing_target
    if target == ProcessingTarget.PR_TRUSTED_DIRECT:
        return PrCommentRouterOutcome.TRUSTED_DIRECT
    if isinstance(target, PrCommentRouterOutcome):
        return target
    if pr_admission is None:
        raise RuntimeError("Trusted direct PR comment handling requires pr_admission")
    return pr_admission.route_outcome
