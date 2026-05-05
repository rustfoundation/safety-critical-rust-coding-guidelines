"""Comment mutation and replay application helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from scripts.reviewer_bot_core import (
    comment_command_policy,
    comment_freshness_policy,
    live_review_support,
    privileged_command_policy,
)

from . import assignment_flow
from . import commands as commands_module
from . import config as config_module
from .context import AssignmentRequest, CommentEventRequest
from .review_state import (
    accept_channel_event,
    ensure_review_entry,
    record_reviewer_activity,
)
from .runtime_protocols import CommentApplicationRuntimeContext


@dataclass(frozen=True)
class CommandExecutionResult:
    response: str
    success: bool
    state_changed: bool


@dataclass(frozen=True)
class ReviewerFeedbackHandoffDecision:
    authorized: bool
    issue_number: int
    actor: str
    source_event_key: str
    timestamp: str
    reviewed_head_sha: str | None
    replace_existing: bool
    response_state: str
    reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "authorized": self.authorized,
            "issue_number": self.issue_number,
            "actor": self.actor,
            "source_event_key": self.source_event_key,
            "timestamp": self.timestamp,
            "reviewed_head_sha": self.reviewed_head_sha,
            "replace_existing": self.replace_existing,
            "response_state": self.response_state,
            "reason": self.reason,
        }


def _route_comment_application(classified: dict, *, comment_id: int) -> str:
    comment_class = str(classified.get("comment_class", ""))
    command_count = int(classified.get("command_count", 0))
    if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:
        if comment_class in {"command_only", "command_plus_text"} and command_count == 1:
            return "both"
        return "freshness_only"
    if comment_class in {"command_only", "command_plus_text"} and command_count == 1:
        return "command_only"
    return "noop"


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
    effective_review_data = dict(review_data)
    if not (request.issue_author and request.issue_author.lower() == request.comment_author.lower()):
        current_reviewer = review_data.get("current_reviewer")
        confirmed_reviewer = None
        if isinstance(current_reviewer, str) and current_reviewer.strip():
            authority = assignment_flow.resolve_reviewer_authority(
                bot,
                issue_number,
                review_data,
                is_pull_request=request.is_pull_request,
            )
            if authority.get("authority_status") == "tracked_reviewer_confirmed":
                confirmed_reviewer = authority.get("tracked_reviewer")
        effective_review_data["current_reviewer"] = confirmed_reviewer
    current_head_sha = review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None
    event = comment_freshness_policy.build_comment_freshness_event(effective_review_data, request)
    decision = comment_freshness_policy.decide_comment_freshness_event(event, current_head_sha=current_head_sha)
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


def _build_assignment_request_from_comment_request(request: CommentEventRequest) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=request.issue_number,
        issue_author=request.issue_author,
        is_pull_request=request.is_pull_request,
        issue_labels=request.issue_labels,
    )


def _build_execution_result(command_id: comment_command_policy.OrdinaryCommandId, result) -> CommandExecutionResult:
    if command_id in {
        comment_command_policy.OrdinaryCommandId.PASS,
        comment_command_policy.OrdinaryCommandId.AWAY,
        comment_command_policy.OrdinaryCommandId.DONE,
        comment_command_policy.OrdinaryCommandId.SYNC_MEMBERS,
        comment_command_policy.OrdinaryCommandId.CLAIM,
        comment_command_policy.OrdinaryCommandId.RELEASE,
        comment_command_policy.OrdinaryCommandId.ASSIGN_SPECIFIC,
        comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE,
    }:
        if len(result) == 3:
            response, success, state_changed = result
            return CommandExecutionResult(response=response, success=success, state_changed=state_changed)
        response, success = result
        return CommandExecutionResult(response=response, success=success, state_changed=success)
    if command_id in {
        comment_command_policy.OrdinaryCommandId.QUEUE,
        comment_command_policy.OrdinaryCommandId.COMMANDS,
    }:
        response, success = result
        return CommandExecutionResult(response=response, success=success, state_changed=False)
    response, success, state_changed = result
    return CommandExecutionResult(response=response, success=success, state_changed=state_changed)


def _execute_pass(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    reviewer_authority = assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        assignment_request,
        actor=decision.actor,
    )
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_pass_command(
            bot,
            state,
            decision.issue_number,
            decision.actor,
            " ".join(decision.raw_args) if decision.raw_args else None,
            request=assignment_request,
            reviewer_authority=reviewer_authority,
        ),
    )


def _execute_away(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_pass_until_command(
            bot,
            state,
            decision.issue_number,
            decision.actor,
            decision.raw_args[0],
            " ".join(decision.raw_args[1:]) if len(decision.raw_args) > 1 else None,
            request=assignment_request,
        ),
    )


def _execute_done(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_done_command(
            bot,
            state,
            decision.issue_number,
            decision.actor,
            request=assignment_request,
        ),
    )


def _execute_label(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_label_command(
            bot,
            state,
            decision.issue_number,
            " ".join(decision.raw_args),
            request=assignment_request,
        ),
    )


def _execute_sync_members(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    del decision, assignment_request
    return _build_execution_result(comment_command_policy.OrdinaryCommandId.SYNC_MEMBERS, commands_module.handle_sync_members_command(bot, state))


def _execute_queue(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    del decision
    if assignment_request is None:
        result = commands_module.handle_queue_command(bot, state)
    else:
        result = commands_module.handle_queue_command(bot, state, request=assignment_request)
    return _build_execution_result(comment_command_policy.OrdinaryCommandId.QUEUE, result)


def _execute_commands(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    del state, decision, assignment_request
    return _build_execution_result(comment_command_policy.OrdinaryCommandId.COMMANDS, commands_module.handle_commands_command(bot))


def _execute_claim(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_claim_command(bot, state, decision.issue_number, decision.actor, request=assignment_request),
    )


def _execute_release(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    reviewer_authority = assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        assignment_request,
        actor=decision.actor,
    )
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_release_command(
            bot,
            state,
            decision.issue_number,
            decision.actor,
            list(decision.raw_args),
            request=assignment_request,
            reviewer_authority=reviewer_authority,
        ),
    )


def _execute_rectify(bot, state: dict, request: CommentEventRequest, decision) -> CommandExecutionResult:
    from . import reconcile as reconcile_module

    reviewer_authority = assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        request,
        actor=decision.actor,
    )
    return _build_execution_result(
        decision.command_id,
        reconcile_module.handle_rectify_command(
            bot,
            state,
            decision.issue_number,
            decision.actor,
            reviewer_authority=reviewer_authority,
        ),
    )


def _handoff_order_key(handoff: dict) -> tuple[object, str] | None:
    timestamp = live_review_support.parse_github_timestamp(handoff.get("timestamp"))
    if timestamp is None:
        return None
    source_event_key = handoff.get("source_event_key")
    return timestamp, source_event_key if isinstance(source_event_key, str) else ""


def _feedback_handoff_should_replace(existing: object, candidate: dict) -> bool:
    if not isinstance(existing, dict):
        return True
    candidate_key = _handoff_order_key(candidate)
    existing_key = _handoff_order_key(existing)
    if candidate_key is None:
        return existing_key is None
    if existing_key is None:
        return True
    candidate_timestamp, candidate_source = candidate_key
    existing_timestamp, existing_source = existing_key
    if candidate_timestamp > existing_timestamp:
        return True
    if candidate_timestamp < existing_timestamp:
        return False
    return candidate_source == existing_source


def build_reviewer_feedback_handoff_decision(
    review_data: dict,
    request: CommentEventRequest,
    authority,
    *,
    current_head_sha: str | None,
) -> ReviewerFeedbackHandoffDecision:
    source_event_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    reviewed_head_sha = current_head_sha if request.is_pull_request else None
    authorized = bool(authority.get("authorized") if isinstance(authority, dict) else False)
    reason = None if authorized else str((authority or {}).get("reason") or "unauthorized")
    handoff = {
        "source_event_key": source_event_key,
        "timestamp": request.comment_created_at,
        "actor": request.comment_author,
        "command_name": comment_command_policy.OrdinaryCommandId.FEEDBACK.value,
        "reviewed_head_sha": reviewed_head_sha,
    }
    replace_existing = _feedback_handoff_should_replace(review_data.get("current_cycle_reviewer_handoff"), handoff)
    return ReviewerFeedbackHandoffDecision(
        authorized=authorized,
        issue_number=request.issue_number,
        actor=request.comment_author,
        source_event_key=source_event_key,
        timestamp=request.comment_created_at,
        reviewed_head_sha=reviewed_head_sha,
        replace_existing=replace_existing,
        response_state="awaiting_contributor_response" if authorized else "projection_failed",
        reason=reason,
    )


def handle_feedback_command(bot, state: dict, request: CommentEventRequest, decision) -> CommandExecutionResult:
    if request.issue_state.lower() != "open":
        return CommandExecutionResult(
            response="❌ `/feedback` can only be used on open tracked review items.",
            success=False,
            state_changed=False,
        )
    authority = assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        request,
        actor=decision.actor,
    )
    if not authority.get("authorized"):
        return CommandExecutionResult(
            response=assignment_flow.reviewer_command_authority_failure_message("feedback", authority),
            success=False,
            state_changed=False,
        )
    review_data = authority.get("review_data")
    if not isinstance(review_data, dict):
        return CommandExecutionResult(response="❌ Unable to load review state.", success=False, state_changed=False)
    reviewed_head_sha = None
    if request.is_pull_request:
        active_head_sha = review_data.get("active_head_sha")
        if not isinstance(active_head_sha, str) or not active_head_sha.strip():
            return CommandExecutionResult(
                response="❌ Unable to record `/feedback`: tracked PR head is unavailable.",
                success=False,
                state_changed=False,
            )
        reviewed_head_sha = active_head_sha
    handoff_decision = build_reviewer_feedback_handoff_decision(
        review_data,
        request,
        authority,
        current_head_sha=reviewed_head_sha,
    )
    handoff = {
        "source_event_key": handoff_decision.source_event_key,
        "timestamp": handoff_decision.timestamp,
        "actor": handoff_decision.actor,
        "command_name": comment_command_policy.OrdinaryCommandId.FEEDBACK.value,
        "reviewed_head_sha": handoff_decision.reviewed_head_sha,
    }
    before = review_data.get("current_cycle_reviewer_handoff")
    if not handoff_decision.replace_existing:
        return CommandExecutionResult(
            response="ℹ️ Ignored stale `/feedback` handoff because a newer or same-time reviewer handoff is already recorded.",
            success=True,
            state_changed=False,
        )
    review_data["current_cycle_reviewer_handoff"] = handoff
    activity_changed = record_reviewer_activity(review_data, request.comment_created_at)
    state_changed = before != handoff or activity_changed
    return CommandExecutionResult(
        response="✅ Recorded reviewer feedback handoff. Reviewer-bot is now waiting on contributor response.",
        success=True,
        state_changed=state_changed,
    )


def _execute_assign_specific(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    username = decision.raw_args[0] if decision.raw_args else ""
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_assign_command(bot, state, decision.issue_number, username, request=assignment_request),
    )


def _execute_assign_from_queue(bot, state: dict, decision, assignment_request: AssignmentRequest | None) -> CommandExecutionResult:
    return _build_execution_result(
        decision.command_id,
        commands_module.handle_assign_from_queue_command(bot, state, decision.issue_number, request=assignment_request),
    )


def _command_skips_freshness_recording(classified: dict) -> bool:
    return classified.get("command") in {
        comment_command_policy.OrdinaryCommandId.FEEDBACK.value,
        "_malformed_feedback_args",
    }


ORDINARY_COMMAND_HANDLERS = {
    comment_command_policy.OrdinaryCommandId.PASS: _execute_pass,
    comment_command_policy.OrdinaryCommandId.AWAY: _execute_away,
    comment_command_policy.OrdinaryCommandId.DONE: _execute_done,
    comment_command_policy.OrdinaryCommandId.LABEL: _execute_label,
    comment_command_policy.OrdinaryCommandId.SYNC_MEMBERS: _execute_sync_members,
    comment_command_policy.OrdinaryCommandId.QUEUE: _execute_queue,
    comment_command_policy.OrdinaryCommandId.COMMANDS: _execute_commands,
    comment_command_policy.OrdinaryCommandId.CLAIM: _execute_claim,
    comment_command_policy.OrdinaryCommandId.RELEASE: _execute_release,
    comment_command_policy.OrdinaryCommandId.RECTIFY: _execute_rectify,
    comment_command_policy.OrdinaryCommandId.ASSIGN_SPECIFIC: _execute_assign_specific,
    comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE: _execute_assign_from_queue,
}


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
    if isinstance(decision, comment_command_policy.IgnoreDecision):
        return False

    issue_number = request.issue_number
    source_event_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if isinstance(decision, comment_command_policy.DeferPrivilegedHandoffDecision):
        review_data = ensure_review_entry(state, issue_number, create=True)
        if review_data is None:
            return False
        permission_status = bot.github.get_user_permission_status(request.comment_author, "triage")
        handoff = privileged_command_policy.validate_accept_no_fls_changes_handoff(
            request,
            permission_status,
            source_event_key=source_event_key,
        )
        if isinstance(handoff, privileged_command_policy.BlockedPrivilegedHandoff):
            bot.github.post_comment(issue_number, handoff.response)
            return False
        pending = privileged_command_policy.build_pending_privileged_command(created_at=request.comment_created_at, handoff=handoff)
        privileged_command_policy.put_pending_accept_no_fls_changes(review_data, pending)
        stored = True
        if stored:
            state_issue_number = bot.state_issue_number()
            if state_issue_number <= 0:
                state_issue_number = int(getattr(bot, "STATE_ISSUE_NUMBER", 0) or 0)
            issue_reference = f"#{state_issue_number}" if state_issue_number > 0 else "the configured state issue"
            bot.github.post_comment(
                issue_number,
                "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. "
                f"Use the isolated privileged workflow to execute it from issue `{issue_reference}` state.",
            )
        return stored

    if isinstance(decision, comment_command_policy.InlineResponseDecision):
        execution = CommandExecutionResult(response=decision.response, success=decision.success, state_changed=False)
        react = decision.react
    else:
        if decision.command_id == comment_command_policy.OrdinaryCommandId.FEEDBACK:
            execution = handle_feedback_command(bot, state, request, decision)
        elif decision.command_id == comment_command_policy.OrdinaryCommandId.RECTIFY:
            execution = _execute_rectify(bot, state, request, decision)
        else:
            assignment_request = (
                _build_assignment_request_from_comment_request(request)
                if decision.needs_assignment_request
                else None
            )
            execution = ORDINARY_COMMAND_HANDLERS[decision.command_id](bot, state, decision, assignment_request)
        react = True

    comment_id = request.comment_id
    if comment_id > 0 and react:
        bot.github.add_reaction(comment_id, "eyes")
        if execution.success:
            bot.github.add_reaction(comment_id, "+1")
    if execution.response:
        bot.github.post_comment(issue_number, execution.response)
    return execution.state_changed


def process_comment_event(
    bot: CommentApplicationRuntimeContext,
    state: dict,
    request: CommentEventRequest,
    *,
    classify_comment_payload,
    classify_issue_comment_actor,
) -> bool:
    comment_id = request.comment_id
    classified = classify_comment_payload(bot, request.comment_body)
    routing = _route_comment_application(classified, comment_id=comment_id)
    state_changed = False
    if routing in {"freshness_only", "both"} and not _command_skips_freshness_recording(classified):
        state_changed = record_conversation_freshness(bot, state, request) or state_changed
    if routing in {"command_only", "both"}:
        state_changed = apply_comment_command(
            bot,
            state,
            request,
            classified,
            classify_issue_comment_actor=classify_issue_comment_actor,
        ) or state_changed
    return state_changed
