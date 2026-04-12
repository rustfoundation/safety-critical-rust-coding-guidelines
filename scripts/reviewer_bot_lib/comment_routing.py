"""Comment payload parsing, trust routing, and direct comment handling."""

from __future__ import annotations

from scripts.reviewer_bot_core import comment_routing_policy
from scripts.reviewer_bot_core.comment_routing_policy import PrCommentRouterOutcome

from .comment_application import (
    normalize_comment_body,
    process_comment_event,
)
from .context import CommentEventRequest, PrCommentAdmission
from .event_inputs import (
    build_comment_event_request as decode_comment_event_request,
)
from .event_inputs import (
    build_pr_comment_admission as decode_pr_comment_admission,
)
from .runtime_protocols import CommentRoutingRuntimeContext


def _log(bot: CommentRoutingRuntimeContext, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def build_comment_event_request(bot: CommentRoutingRuntimeContext, *, issue_number: int | None = None) -> CommentEventRequest:
    return decode_comment_event_request(bot, issue_number=issue_number)


def build_pr_comment_admission(bot: CommentRoutingRuntimeContext) -> PrCommentAdmission | None:
    return decode_pr_comment_admission(bot)


def _resolve_comment_request(bot: CommentRoutingRuntimeContext, request: CommentEventRequest | None, *, issue_number: int | None = None) -> CommentEventRequest:
    return request or build_comment_event_request(bot, issue_number=issue_number)


def _resolve_pr_admission(bot: CommentRoutingRuntimeContext, pr_admission: PrCommentAdmission | None) -> PrCommentAdmission | None:
    return pr_admission or build_pr_comment_admission(bot)


def _resolve_pr_admission_for_request(
    bot: CommentRoutingRuntimeContext,
    request: CommentEventRequest,
    pr_admission: PrCommentAdmission | None,
) -> PrCommentAdmission | None:
    return pr_admission or decode_pr_comment_admission(bot, request)


def _require_v18_for_pr(bot: CommentRoutingRuntimeContext, state: dict, request: CommentEventRequest, context: str) -> bool:
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


def _comment_line_is_command(bot: CommentRoutingRuntimeContext, line: str) -> bool:
    return comment_routing_policy.comment_line_is_command(bot.BOT_MENTION, line)


def classify_comment_payload(bot: CommentRoutingRuntimeContext, body: str) -> dict:
    normalized = _normalize_comment_body(bot.adapters.commands.strip_code_blocks(body))
    parsed = bot.adapters.commands.parse_command(normalized)
    return comment_routing_policy.classify_comment_payload(bot.BOT_MENTION, normalized, parsed)


def _classify_issue_comment_actor(request: CommentEventRequest) -> str:
    return comment_routing_policy.classify_issue_comment_actor(request)


def classify_issue_comment_actor(request: CommentEventRequest | None = None) -> str:
    if request is None:
        raise RuntimeError("classify_issue_comment_actor requires an explicit request or runtime-aware caller")
    return _classify_issue_comment_actor(request)


def _is_self_comment(bot: CommentRoutingRuntimeContext, author: str) -> bool:
    return author.strip().lower() == bot.BOT_NAME.lower() or author.strip().lower() == bot.BOT_MENTION.lstrip("@").lower()


def _classify_pr_comment_processing_target(
    bot: CommentRoutingRuntimeContext,
    request: CommentEventRequest,
    pr_admission: PrCommentAdmission,
):
    actor_class = _classify_issue_comment_actor(request)
    return comment_routing_policy.classify_pr_comment_processing_target(
        request,
        pr_admission,
        actor_class=actor_class,
        is_self_comment=_is_self_comment(bot, request.comment_author),
    )


def classify_pr_comment_processing_target(
    bot: CommentRoutingRuntimeContext,
    issue_number: int,
    request: CommentEventRequest | None = None,
    pr_admission: PrCommentAdmission | None = None,
):
    comment_request = _resolve_comment_request(bot, request, issue_number=issue_number)
    resolved_admission = _resolve_pr_admission_for_request(bot, comment_request, pr_admission)
    if resolved_admission is None:
        raise RuntimeError("Trusted direct PR comment handling requires pr_admission")
    return _classify_pr_comment_processing_target(
        bot,
        comment_request,
        resolved_admission,
    )


def _route_issue_comment_trust(
    bot: CommentRoutingRuntimeContext,
    request: CommentEventRequest,
    pr_admission: PrCommentAdmission | None,
):
    processing_target = None
    if request.is_pull_request:
        if pr_admission is None:
            raise RuntimeError("Trusted direct PR comment handling requires pr_admission")
        processing_target = _classify_pr_comment_processing_target(bot, request, pr_admission)
    return comment_routing_policy.route_issue_comment_trust(
        request,
        pr_admission,
        processing_target=processing_target,
    )


def route_issue_comment_trust(
    bot: CommentRoutingRuntimeContext,
    issue_number: int,
    request: CommentEventRequest | None = None,
    pr_admission: PrCommentAdmission | None = None,
):
    comment_request = _resolve_comment_request(bot, request, issue_number=issue_number)
    return _route_issue_comment_trust(
        bot,
        comment_request,
        _resolve_pr_admission_for_request(bot, comment_request, pr_admission),
    )


def _process_comment_event(bot: CommentRoutingRuntimeContext, state: dict, request: CommentEventRequest) -> bool:
    return process_comment_event(
        bot,
        state,
        request,
        classify_comment_payload=classify_comment_payload,
        classify_issue_comment_actor=_classify_issue_comment_actor,
    )


def handle_comment_event(
    bot: CommentRoutingRuntimeContext,
    state: dict,
    request: CommentEventRequest | None = None,
    pr_admission: PrCommentAdmission | None = None,
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
        _resolve_pr_admission_for_request(bot, comment_request, pr_admission),
    )
    if route == PrCommentRouterOutcome.SAFE_NOOP:
        return False
    if route == comment_routing_policy.ProcessingTarget.ISSUE_DIRECT:
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
    if route == PrCommentRouterOutcome.TRUSTED_DIRECT:
        if comment_request.issue_state != "open":
            return False
        if not _require_v18_for_pr(bot, state, comment_request, "pr_trusted_direct_comment"):
            return False
        return _process_comment_event(bot, state, comment_request)
    raise RuntimeError("Deferred PR comment events must not mutate directly in trusted workflows")
