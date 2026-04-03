"""Comment payload parsing, trust routing, and direct comment handling."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .comment_application import (
    digest_comment_body,
    normalize_comment_body,
    process_comment_event,
)
from .context import CommentEventRequest, PrCommentTrustContext
from .event_inputs import (
    build_comment_event_request as decode_comment_event_request,
)
from .event_inputs import (
    build_pr_comment_trust_context as decode_pr_comment_trust_context,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def build_comment_event_request(bot, *, issue_number: int | None = None) -> CommentEventRequest:
    return decode_comment_event_request(bot, issue_number=issue_number)


def build_pr_comment_trust_context(bot) -> PrCommentTrustContext:
    return decode_pr_comment_trust_context(bot)


def _require_v18_for_pr(state: dict, request: CommentEventRequest, context: str) -> bool:
    if not request.is_pull_request:
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        print(f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True


def _normalize_comment_body(body: str) -> str:
    return normalize_comment_body(body)


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def _digest_body(body: str) -> str:
    return digest_comment_body(body)


def _comment_line_is_command(bot, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    pattern = rf"^{re.escape(bot.BOT_MENTION)}\s+/[A-Za-z0-9?_-]+(?:\s+.*)?$"
    return re.match(pattern, stripped) is not None


def classify_comment_payload(bot, body: str) -> dict:
    normalized = _normalize_comment_body(bot.strip_code_blocks(body))
    if not normalized:
        return {
            "comment_class": "empty_or_whitespace",
            "has_non_command_text": False,
            "command_count": 0,
            "command": None,
            "args": [],
            "normalized_body": normalized,
        }
    lines = [line for line in normalized.splitlines() if line.strip()]
    command_lines = [line for line in lines if _comment_line_is_command(bot, line)]
    non_command_lines = [line for line in lines if not _comment_line_is_command(bot, line)]
    parsed = bot.parse_command(normalized)
    command = None
    args: list[str] = []
    if parsed:
        command, args = parsed
    if command_lines and not non_command_lines:
        comment_class = "command_only"
    elif command_lines and non_command_lines:
        comment_class = "command_plus_text"
    else:
        comment_class = "plain_text"
    return {
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "command_count": len(command_lines),
        "command": command,
        "args": args,
        "normalized_body": normalized,
    }


def _classify_issue_comment_actor(request: CommentEventRequest) -> str:
    comment_user_type = request.comment_user_type
    comment_author = request.comment_author.strip()
    sender_type = request.comment_sender_type
    installation_id = request.comment_installation_id
    via_github_app = request.comment_performed_via_github_app
    if comment_user_type == "Bot" or comment_author.endswith("[bot]"):
        return "bot_account"
    if installation_id or via_github_app or (sender_type and sender_type not in {"User", "Bot"}):
        return "github_app_or_other_automation"
    if comment_user_type == "User" and comment_author and not comment_author.endswith("[bot]") and not installation_id and not via_github_app:
        return "repo_user_principal"
    return "unknown_actor"


def classify_issue_comment_actor(request: CommentEventRequest | None = None) -> str:
    if request is None:
        raise RuntimeError("classify_issue_comment_actor requires an explicit request or runtime-aware caller")
    return _classify_issue_comment_actor(request)


def _is_self_comment(bot, author: str) -> bool:
    return author.strip().lower() == bot.BOT_NAME.lower() or author.strip().lower() == bot.BOT_MENTION.lstrip("@").lower()


def _fetch_pr_metadata(bot, issue_number: int) -> dict:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch live PR metadata for #{issue_number}")
    if not isinstance(pull_request.get("head"), dict) or not isinstance(pull_request.get("user"), dict):
        raise RuntimeError(f"Unusable PR metadata for #{issue_number}")
    return pull_request


def _classify_pr_comment_processing_target(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> str:
    actor_class = _classify_issue_comment_actor(request)
    if actor_class in {"bot_account", "github_app_or_other_automation"} or _is_self_comment(bot, request.comment_author):
        return "safe_noop"
    pull_request = _fetch_pr_metadata(bot, request.issue_number)
    head_repo = pull_request.get("head", {}).get("repo", {})
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if not isinstance(head_full_name, str) or not head_full_name:
        raise RuntimeError("Missing PR head repository metadata for trust routing")
    is_cross_repo = head_full_name != trust_context.github_repository
    pr_author = pull_request.get("user", {}).get("login")
    is_dependabot_restricted = pr_author == "dependabot[bot]"
    author_association = trust_context.comment_author_association
    trusted_principal = actor_class == "repo_user_principal" and author_association in bot.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
    if is_cross_repo or is_dependabot_restricted:
        return "pr_deferred_reconcile"
    if trusted_principal:
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def classify_pr_comment_processing_target(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = request or build_comment_event_request(bot, issue_number=issue_number)
    return _classify_pr_comment_processing_target(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(bot),
    )


def _route_issue_comment_trust(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> str:
    if not request.is_pull_request:
        return "issue_direct"
    target = _classify_pr_comment_processing_target(bot, request, trust_context)
    if target != "pr_trusted_direct":
        return target
    workflow_file = trust_context.current_workflow_file
    workflow_ref = trust_context.github_ref
    if workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml" and workflow_ref == "refs/heads/main":
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def route_issue_comment_trust(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = request or build_comment_event_request(bot, issue_number=issue_number)
    return _route_issue_comment_trust(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(bot),
    )


def _build_pr_comment_observer_payload(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> dict:
    actor_class = _classify_issue_comment_actor(request)
    comment_id = request.comment_id
    base_payload = {
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": trust_context.github_run_id,
        "source_run_attempt": trust_context.github_run_attempt,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": f"issue_comment:{comment_id}",
        "pr_number": request.issue_number,
    }
    if actor_class in {"bot_account", "github_app_or_other_automation"} or _is_self_comment(bot, request.comment_author):
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "ignored_non_human_automation",
            **base_payload,
        }
    processing_target = _classify_pr_comment_processing_target(bot, request, trust_context)
    if processing_target == "pr_trusted_direct":
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "trusted_direct_same_repo_human_comment",
            **base_payload,
        }
    body = request.comment_body
    normalized = _normalize_comment_body(body)
    command_pattern = re.compile(r"^@guidelines\-bot\s+/[A-Za-z0-9?_\-]+(?:\s+.*)?$")
    lines = [line for line in normalized.splitlines() if line.strip()]
    command_lines = [line for line in lines if command_pattern.match(line.strip())]
    non_command_lines = [line for line in lines if not command_pattern.match(line.strip())]
    if not normalized:
        comment_class = "empty_or_whitespace"
    elif command_lines and not non_command_lines:
        comment_class = "command_only"
    elif command_lines and non_command_lines:
        comment_class = "command_plus_text"
    else:
        comment_class = "plain_text"
    return {
        "schema_version": 2,
        **base_payload,
        "comment_id": comment_id,
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "source_body_digest": _digest_body(body),
        "source_created_at": request.comment_created_at,
        "actor_login": request.comment_author,
        "actor_id": request.comment_author_id,
        "actor_class": "repo_user_principal" if actor_class == "repo_user_principal" else "unknown_actor",
        "source_artifact_name": (
            f"reviewer-bot-comment-context-{trust_context.github_run_id}-attempt-"
            f"{trust_context.github_run_attempt}"
        ),
    }


def build_pr_comment_observer_payload(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> dict:
    comment_request = request or build_comment_event_request(bot, issue_number=issue_number)
    return _build_pr_comment_observer_payload(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(bot),
    )


def _process_comment_event(bot, state: dict, request: CommentEventRequest) -> bool:
    return process_comment_event(
        bot,
        state,
        request,
        classify_comment_payload=classify_comment_payload,
        classify_issue_comment_actor=_classify_issue_comment_actor,
    )


def handle_comment_event(
    bot,
    state: dict,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> bool:
    bot.assert_lock_held("handle_comment_event")
    comment_request = request or build_comment_event_request(bot)
    issue_number = comment_request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    route = _route_issue_comment_trust(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(bot),
    )
    if route == "safe_noop":
        return False
    if route == "issue_direct":
        if comment_request.issue_state == "closed":
            removed = state.get("active_reviews", {}).pop(str(issue_number), None)
            print(f"Ignoring direct comment on closed issue #{issue_number}")
            return removed is not None
        return _process_comment_event(bot, state, comment_request)
    if route == "pr_trusted_direct":
        if not _require_v18_for_pr(state, comment_request, "pr_trusted_direct_comment"):
            return False
        return _process_comment_event(bot, state, comment_request)
    raise RuntimeError("Deferred PR comment events must not mutate directly in trusted workflows")
