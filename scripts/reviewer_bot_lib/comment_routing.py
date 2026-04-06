"""Comment payload parsing, trust routing, and direct comment handling."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from scripts.reviewer_bot_core import comment_routing_policy

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


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


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


def _resolve_comment_request(bot, request: CommentEventRequest | None, *, issue_number: int | None = None) -> CommentEventRequest:
    return request or build_comment_event_request(bot, issue_number=issue_number)


def _resolve_trust_context(bot, trust_context: PrCommentTrustContext | None) -> PrCommentTrustContext:
    return trust_context or build_pr_comment_trust_context(bot)


def _require_v18_for_pr(bot, state: dict, request: CommentEventRequest, context: str) -> bool:
    if not request.is_pull_request:
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        _log(
            bot,
            "info",
            f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}",
            context=context,
            runtime_epoch=epoch,
        )
        return False
    return True


def _normalize_comment_body(body: str) -> str:
    return normalize_comment_body(body)


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def _digest_body(body: str) -> str:
    return digest_comment_body(body)


def _comment_line_is_command(bot, line: str) -> bool:
    return comment_routing_policy.comment_line_is_command(bot.BOT_MENTION, line)


def classify_comment_payload(bot, body: str) -> dict:
    normalized = _normalize_comment_body(bot.adapters.commands.strip_code_blocks(body))
    parsed = bot.adapters.commands.parse_command(normalized)
    return comment_routing_policy.classify_comment_payload(bot.BOT_MENTION, normalized, parsed)


def _classify_issue_comment_actor(request: CommentEventRequest) -> str:
    return comment_routing_policy.classify_issue_comment_actor(request)


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
    pull_request = _fetch_pr_metadata(bot, request.issue_number)
    head_repo = pull_request.get("head", {}).get("repo", {})
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    pr_author = pull_request.get("user", {}).get("login")
    return comment_routing_policy.classify_pr_comment_processing_target(
        request,
        trust_context,
        actor_class=actor_class,
        is_self_comment=_is_self_comment(bot, request.comment_author),
        pr_head_full_name=head_full_name,
        pr_author=pr_author if isinstance(pr_author, str) else None,
        author_association_trust_allowlist=bot.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
    )


def classify_pr_comment_processing_target(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = _resolve_comment_request(bot, request, issue_number=issue_number)
    return _classify_pr_comment_processing_target(
        bot,
        comment_request,
        _resolve_trust_context(bot, trust_context),
    )


def _route_issue_comment_trust(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> str:
    processing_target = None
    if request.is_pull_request:
        processing_target = _classify_pr_comment_processing_target(bot, request, trust_context)
    return comment_routing_policy.route_issue_comment_trust(
        request,
        trust_context,
        processing_target=processing_target,
    )


def route_issue_comment_trust(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = _resolve_comment_request(bot, request, issue_number=issue_number)
    return _route_issue_comment_trust(
        bot,
        comment_request,
        _resolve_trust_context(bot, trust_context),
    )


def _build_pr_comment_observer_payload(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> dict:
    actor_class = _classify_issue_comment_actor(request)
    processing_target = _classify_pr_comment_processing_target(bot, request, trust_context)
    body = request.comment_body
    payload_classification = classify_comment_payload(bot, body)
    if _is_self_comment(bot, request.comment_author):
        actor_class = "bot_account"
    return comment_routing_policy.build_pr_comment_observer_payload(
        request,
        trust_context,
        actor_class=actor_class,
        processing_target=processing_target,
        payload_classification=payload_classification,
        body_digest=_digest_body(body),
    )


def build_pr_comment_observer_payload(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> dict:
    comment_request = _resolve_comment_request(bot, request, issue_number=issue_number)
    return _build_pr_comment_observer_payload(
        bot,
        comment_request,
        _resolve_trust_context(bot, trust_context),
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
    comment_request = _resolve_comment_request(bot, request)
    issue_number = comment_request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    route = _route_issue_comment_trust(
        bot,
        comment_request,
        _resolve_trust_context(bot, trust_context),
    )
    if route == "safe_noop":
        return False
    if route == "issue_direct":
        if comment_request.issue_state == "closed":
            removed = state.get("active_reviews", {}).pop(str(issue_number), None)
            _log(
                bot,
                "info",
                f"Ignoring direct comment on closed issue #{issue_number}",
                issue_number=issue_number,
                issue_state=comment_request.issue_state,
            )
            return removed is not None
        return _process_comment_event(bot, state, comment_request)
    if route == "pr_trusted_direct":
        if not _require_v18_for_pr(bot, state, comment_request, "pr_trusted_direct_comment"):
            return False
        return _process_comment_event(bot, state, comment_request)
    raise RuntimeError("Deferred PR comment events must not mutate directly in trusted workflows")
