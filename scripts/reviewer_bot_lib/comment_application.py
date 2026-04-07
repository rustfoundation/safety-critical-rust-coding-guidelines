"""Comment mutation and replay application helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from scripts.reviewer_bot_core import (
    comment_command_policy,
    comment_freshness_policy,
    privileged_command_policy,
)

from . import commands as commands_module
from . import config as config_module
from .context import (
    AssignmentRequest,
    CommentApplicationRuntimeContext,
    CommentEventRequest,
)
from .review_state import (
    accept_channel_event,
    ensure_review_entry,
    record_reviewer_activity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


@dataclass(frozen=True)
class CommentApplicationRoutingResult:
    kind: str


def _route_comment_application(classified: dict, *, comment_id: int) -> CommentApplicationRoutingResult:
    comment_class = str(classified.get("comment_class", ""))
    command_count = int(classified.get("command_count", 0))
    if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:
        if comment_class in {"command_only", "command_plus_text"} and command_count == 1:
            return CommentApplicationRoutingResult(kind="both")
        return CommentApplicationRoutingResult(kind="freshness_only")
    if comment_class in {"command_only", "command_plus_text"} and command_count == 1:
        return CommentApplicationRoutingResult(kind="command_only")
    return CommentApplicationRoutingResult(kind="noop")


def normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def digest_comment_body(body: str) -> str:
    return hashlib.sha256(normalize_comment_body(body).encode("utf-8")).hexdigest()


def record_conversation_freshness(
    bot: CommentApplicationRuntimeContext,
    state: dict,
    request: CommentEventRequest,
) -> bool:
    issue_number = request.issue_number
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    decision = comment_freshness_policy.decide_comment_freshness(review_data, request)
    if decision.kind != "accept_channel_event":
        return False
    changed = accept_channel_event(
        review_data,
        str(decision.channel_name),
        semantic_key=str(decision.semantic_key),
        timestamp=str(decision.timestamp),
        actor=str(decision.actor),
    )
    if decision.update_reviewer_activity:
        previous_activity = review_data.get("last_reviewer_activity")
        previous_warning = review_data.get("transition_warning_sent")
        previous_notice = review_data.get("transition_notice_sent_at")
        record_reviewer_activity(review_data, str(decision.timestamp))
        activity_changed = (
            previous_activity != review_data.get("last_reviewer_activity")
            or previous_warning != review_data.get("transition_warning_sent")
            or previous_notice != review_data.get("transition_notice_sent_at")
        )
        return changed or activity_changed
    return changed


def build_assignment_request_from_comment(request: CommentEventRequest) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=request.issue_number,
        issue_author=request.issue_author,
        is_pull_request=request.is_pull_request,
    )


def validate_accept_no_fls_changes_handoff(
    bot: CommentApplicationRuntimeContext,
    request: CommentEventRequest,
) -> tuple[bool, dict]:
    labels = commands_module.parse_issue_labels(bot)
    permission_status = bot.github.get_user_permission_status(request.comment_author, "triage")
    decision = privileged_command_policy.validate_accept_no_fls_changes_handoff(request, labels, permission_status)
    return decision.kind == "handoff_allowed", dict(decision.metadata or {})


def apply_comment_command(
    bot: CommentApplicationRuntimeContext,
    state: dict,
    request: CommentEventRequest,
    classified: dict,
    *,
    classify_issue_comment_actor,
) -> bool:
    actor_class = classify_issue_comment_actor(request)
    decision = comment_command_policy.decide_comment_command(
        bot,
        request,
        classified,
        actor_class=actor_class,
        commands_help=config_module.get_commands_help(),
    )
    if isinstance(decision, dict) and decision["kind"] == "ignore":
        return False

    issue_number = request.issue_number
    comment_author = request.comment_author
    command = classified.get("command")
    args = classified.get("args") or []
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    source_event_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if isinstance(decision, dict) and decision["kind"] == "deferred_privileged_handoff":
        is_valid, metadata = validate_accept_no_fls_changes_handoff(bot, request)
        if not is_valid:
            bot.github.post_comment(
                issue_number,
                "❌ This command is not eligible for privileged handoff from the current trusted live state.",
            )
            return False
        pending = privileged_command_policy.build_pending_privileged_command(
            source_event_key=source_event_key,
            command_name=str(command),
            issue_number=issue_number,
            actor=comment_author,
            args=list(args),
            created_at=_now_iso(),
            metadata=metadata,
        )
        review_data.setdefault("pending_privileged_commands", {})[source_event_key] = pending.data
        stored = True
        if stored:
            bot.github.post_comment(
                issue_number,
                "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
            )
        return stored

    response = ""
    success = False
    state_changed = False
    assignment_request = build_assignment_request_from_comment(request)
    if decision.kind == "handler_call":
        handler = getattr(commands_module, str(decision.handler_name))
        handler_args = [bot, state, *(decision.handler_args or [])]
        handler_kwargs = {}
        if decision.needs_assignment_request:
            handler_kwargs["request"] = assignment_request
        result = handler(*handler_args, **handler_kwargs)
        if decision.result_shape == "pair":
            response, success = result
            state_changed = success if decision.state_changed_from == "success" else False
        else:
            response, success, state_changed = result
    else:
        response = str(decision.response or "")
        success = bool(decision.success)
        state_changed = False

    comment_id = request.comment_id
    if comment_id > 0 and decision.react:
        bot.github.add_reaction(comment_id, "eyes")
        if success:
            bot.github.add_reaction(comment_id, "+1")
    if response:
        bot.github.post_comment(issue_number, response)
    return state_changed


def process_comment_event(
    bot: CommentApplicationRuntimeContext,
    state: dict,
    request: CommentEventRequest,
    *,
    classify_comment_payload,
    classify_issue_comment_actor,
) -> bool:
    comment_id = request.comment_id
    comment_created_at = request.comment_created_at or _now_iso()
    comment_request = CommentEventRequest(**{**request.__dict__, "comment_created_at": comment_created_at})
    classified = classify_comment_payload(bot, comment_request.comment_body)
    routing = _route_comment_application(classified, comment_id=comment_id)
    state_changed = False
    if routing.kind in {"freshness_only", "both"}:
        state_changed = record_conversation_freshness(bot, state, comment_request) or state_changed
    if routing.kind in {"command_only", "both"}:
        state_changed = apply_comment_command(
            bot,
            state,
            comment_request,
            classified,
            classify_issue_comment_actor=classify_issue_comment_actor,
        ) or state_changed
    return state_changed
