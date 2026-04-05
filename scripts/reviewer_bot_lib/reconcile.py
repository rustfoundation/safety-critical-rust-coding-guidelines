"""Trusted deferred reconcile helpers for reviewer-bot workflow_run processing."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .comment_application import (
    digest_comment_body,
    process_comment_event,
    record_conversation_freshness,
)
from .comment_routing import classify_comment_payload, classify_issue_comment_actor
from .context import CommentEventRequest
from .reconcile_payloads import (
    DeferredCommentPayload,
    DeferredCommentReplayContext,
    DeferredReviewPayload,
    ObserverNoopPayload,
    build_deferred_comment_replay_context,
    build_deferred_review_replay_context,
    parse_deferred_context_payload,
)
from .reconcile_payloads import (
    expected_observer_identity as _expected_observer_identity,
)
from .reconcile_reads import (
    LiveCommentReplayContext,
    ReconcileReadError,
)
from .reconcile_reads import (
    read_live_comment_replay_context as _read_live_comment_replay_context,
)
from .reconcile_reads import (
    read_live_pr_replay_context as _read_live_pr_replay_context,
)
from .reconcile_reads import (
    read_optional_reconcile_object as _read_optional_reconcile_object,
)
from .reconcile_reads import (
    read_reconcile_object as _read_reconcile_object,
)
from .reconcile_reads import (
    read_reconcile_reviews as _read_reconcile_reviews,
)
from .review_state import (
    accept_channel_event,
    ensure_review_entry,
    record_reviewer_activity,
)
from .reviews import (
    find_triage_approval_after,
    rebuild_pr_approval_state_result,
    refresh_reviewer_review_from_live_preferred_review,
)


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


@dataclass(frozen=True)
class LiveCommentReplayValidationResult:
    live_classified: dict | None
    changed: bool
    failed_closed: bool


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    review_data.setdefault("deferred_gaps", {})
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    review_data["deferred_gaps"][source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> bool:
    deferred_gaps = review_data.get("deferred_gaps")
    if isinstance(deferred_gaps, dict):
        if source_event_key in deferred_gaps:
            deferred_gaps.pop(source_event_key, None)
            return True
    return False


def _mark_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.setdefault("reconciled_source_events", [])
    if source_event_key not in reconciled:
        reconciled.append(source_event_key)
        return True
    return False


def _was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.get("reconciled_source_events")
    return isinstance(reconciled, list) and source_event_key in reconciled


def _record_review_rebuild(bot, state: dict, issue_number: int, review_data: dict) -> bool:
    pull_request = _read_reconcile_object(bot, f"pulls/{issue_number}", label=f"pull request #{issue_number}")
    reviews = _read_reconcile_reviews(bot, issue_number)
    before = {
        "reviewer_review": deepcopy(review_data.get("reviewer_review")),
        "active_head_sha": review_data.get("active_head_sha"),
        "current_cycle_completion": deepcopy(review_data.get("current_cycle_completion")),
        "current_cycle_write_approval": deepcopy(review_data.get("current_cycle_write_approval")),
        "review_completed_at": review_data.get("review_completed_at"),
        "review_completed_by": review_data.get("review_completed_by"),
        "review_completion_source": review_data.get("review_completion_source"),
    }
    refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
        actor=review_data.get("current_reviewer"),
    )
    approval_result = rebuild_pr_approval_state_result(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if not approval_result.get("ok"):
        raise ReconcileReadError(
            f"Unable to rebuild approval state for PR #{issue_number}: {approval_result.get('reason')}",
            failure_kind=str(approval_result.get("failure_kind") or "unavailable"),
        )
    completion = approval_result["completion"]
    after = {
        "reviewer_review": deepcopy(review_data.get("reviewer_review")),
        "active_head_sha": review_data.get("active_head_sha"),
        "current_cycle_completion": deepcopy(review_data.get("current_cycle_completion")),
        "current_cycle_write_approval": deepcopy(review_data.get("current_cycle_write_approval")),
        "review_completed_at": review_data.get("review_completed_at"),
        "review_completed_by": review_data.get("review_completed_by"),
        "review_completion_source": review_data.get("review_completion_source"),
    }
    return before != after or bool(completion.get("completed"))


def reconcile_active_review_entry(
    bot,
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False
    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.", True, False
    if require_pull_request_context and bot.get_config_value("IS_PULL_REQUEST", "false").lower() != "true":
        return f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only reconciles PR reviews.", True, False
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15" and bot.get_config_value("IS_PULL_REQUEST", "false").lower() == "true":
        return "ℹ️ PR review freshness rectify is epoch-gated and currently inactive.", True, False
    head_repair_result = bot.adapters.review_state.maybe_record_head_observation_repair(issue_number, review_data)
    state_changed = head_repair_result.changed
    try:
        reviews = _read_reconcile_reviews(bot, issue_number)
    except ReconcileReadError:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False
    messages: list[str] = []
    refreshed, latest_review = refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        reviews=reviews,
        actor=assigned_reviewer,
    )
    if latest_review is not None:
        latest_state = str(latest_review.get("state", "")).upper()
        if refreshed:
            state_changed = True
            messages.append(f"latest review by @{assigned_reviewer} is `{latest_state}`")
    if _record_review_rebuild(bot, state, issue_number, review_data):
        state_changed = True
        review_data["review_completion_source"] = completion_source
    if review_data.get("mandatory_approver_required"):
        escalation_opened_at = bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at")) or bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        triage_approval = find_triage_approval_after(bot, reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if bot.satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")
    if state_changed:
        return f"✅ Rectified PR #{issue_number}: {'; '.join(messages) or 'reconciled live review state'}.", True, True
    return f"ℹ️ Rectify checked PR #{issue_number}: {'; '.join(messages) or 'no reconciliation transitions applied'}.", True, False


def handle_rectify_command(bot, state: dict, issue_number: int, comment_author: str) -> tuple[str, bool, bool]:
    review_data = ensure_review_entry(state, issue_number)
    current_reviewer = review_data.get("current_reviewer") if review_data else None

    is_current_reviewer = (
        isinstance(current_reviewer, str)
        and current_reviewer.lower() == comment_author.lower()
    )

    triage_status = "denied"
    if not is_current_reviewer:
        triage_status = bot.github.get_user_permission_status(comment_author, "triage")

    if not is_current_reviewer and triage_status == "unavailable":
        return (
            "❌ Unable to verify triage permissions right now; refusing to continue.",
            False,
            False,
        )

    if not is_current_reviewer and triage_status != "granted":
        if current_reviewer:
            return (
                f"❌ Only the assigned reviewer (@{current_reviewer}) or a maintainer with triage+ "
                "permission can run `/rectify`.",
                False,
                False,
            )
        return (
            "❌ Only maintainers with triage+ permission can run `/rectify` when no assigned "
            "reviewer is tracked.",
            False,
            False,
        )

    return reconcile_active_review_entry(bot, state, issue_number)


def _validate_deferred_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred comment artifact source digest or timestamp is malformed")


def _validate_deferred_review_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "review_id",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("review_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review artifact review_id and pr_number must be integers")


def _validate_deferred_review_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review-comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review-comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review-comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred review-comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred review-comment artifact source digest or timestamp is malformed")


def _load_deferred_context(bot) -> dict:
    return bot.load_deferred_payload()


def _validate_workflow_run_artifact_identity(bot, payload: dict) -> None:
    expected_name, expected_file = _expected_observer_identity(payload)
    if payload.get("source_workflow_name") != expected_name:
        raise RuntimeError("Deferred artifact workflow name mismatch")
    if payload.get("source_workflow_file") != expected_file:
        raise RuntimeError("Deferred artifact workflow file mismatch")
    triggering_name = bot.get_config_value("WORKFLOW_RUN_TRIGGERING_NAME").strip()
    if triggering_name and triggering_name != expected_name:
        raise RuntimeError("Triggering workflow name mismatch")
    triggering_id = bot.get_config_value("WORKFLOW_RUN_TRIGGERING_ID").strip()
    if triggering_id and str(payload.get("source_run_id")) != triggering_id:
        raise RuntimeError("Deferred artifact run_id mismatch")
    triggering_attempt = bot.get_config_value("WORKFLOW_RUN_TRIGGERING_ATTEMPT").strip()
    if triggering_attempt and str(payload.get("source_run_attempt")) != triggering_attempt:
        raise RuntimeError("Deferred artifact run_attempt mismatch")
    if bot.get_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION").strip() != "success":
        raise RuntimeError("Triggering observer workflow did not conclude successfully")


def _reconcile_deferred_comment(
    bot,
    state: dict,
    review_data: dict,
    context: DeferredCommentReplayContext,
) -> bool:
    payload = context.payload.raw_payload
    comment_id = context.comment_id
    pr_number = context.pr_number
    pr_context = _read_live_pr_replay_context(bot, pr_number)
    comment_author = context.actor_login
    comment_created_at = context.source_created_at
    source_freshness_eligible = context.source_freshness_eligible

    def replay_request(comment_context: LiveCommentReplayContext | None = None, *, comment_body: str = "") -> CommentEventRequest:
        return CommentEventRequest(
            issue_number=pr_number,
            is_pull_request=True,
            issue_author=pr_context.issue_author,
            comment_id=comment_id,
            comment_author=(comment_context.comment_author if comment_context is not None else (comment_author or "")),
            comment_body=comment_body,
            comment_created_at=comment_created_at,
            comment_source_event_key=context.source_event_key,
            comment_user_type=(comment_context.comment_user_type if comment_context is not None else ""),
            comment_sender_type=(comment_context.comment_sender_type if comment_context is not None else ""),
            comment_installation_id=(comment_context.comment_installation_id if comment_context is not None else ""),
            comment_performed_via_github_app=(
                comment_context.comment_performed_via_github_app if comment_context is not None else False
            ),
        )

    try:
        live_comment = _read_reconcile_object(bot, context.live_comment_endpoint, label=f"deferred comment {comment_id}")
    except ReconcileReadError as exc:
        changed = False
        if source_freshness_eligible:
            changed = record_conversation_freshness(bot, state, replay_request())
        if exc.failure_kind == "not_found":
            summary = (
                f"Deferred comment {comment_id} is no longer visible; source-time freshness only may be preserved. "
                f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            )
        else:
            summary = (
                f"Deferred comment {comment_id} could not be validated from live GitHub data "
                f"({exc.failure_kind or 'unavailable'}); replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            )
        gap_changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            summary,
            failure_kind=exc.failure_kind,
        )
        return changed or gap_changed
    comment_context = _read_live_comment_replay_context(live_comment, payload)
    live_body = live_comment.get("body")
    if not isinstance(live_body, str):
        raise RuntimeError("Live deferred comment body is unavailable")
    if digest_comment_body(live_body) != payload.get("source_body_digest"):
        changed = False
        if source_freshness_eligible:
            changed = record_conversation_freshness(bot, state, replay_request(comment_context, comment_body=live_body))
        gap_changed = _update_deferred_gap(bot, review_data, payload, "reconcile_failed_closed", f"Deferred comment {comment_id} body digest changed; command execution suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
        return changed or gap_changed
    changed = False
    if source_freshness_eligible:
        changed = record_conversation_freshness(bot, state, replay_request(comment_context, comment_body=live_body)) or changed
    validation_result = _validate_live_comment_replay_contract(
        bot,
        review_data,
        payload,
        live_body,
    )
    if validation_result.live_classified is None:
        return changed or validation_result.changed
    live_classified = validation_result.live_classified
    if context.payload.comment_class in {"command_only", "command_plus_text"}:
        changed = process_comment_event(
            bot,
            state,
            replay_request(comment_context, comment_body=live_body),
            classify_comment_payload=lambda _bot, _body: live_classified,
            classify_issue_comment_actor=classify_issue_comment_actor,
        ) or changed
    reconciled_changed = _mark_reconciled_source_event(review_data, str(payload.get("source_event_key", "")))
    gap_cleared_changed = _clear_source_event_key(review_data, str(payload.get("source_event_key", "")))
    return changed or reconciled_changed or gap_cleared_changed


def _update_deferred_gap(
    bot,
    review_data: dict,
    payload: dict,
    reason: str,
    diagnostic_summary: str,
    *,
    failure_kind: str | None = None,
) -> bool:
    source_event_key = str(payload.get("source_event_key", ""))
    if not source_event_key:
        return False
    review_data.setdefault("deferred_gaps", {})
    existing = review_data["deferred_gaps"].get(source_event_key, {})
    if not isinstance(existing, dict):
        existing = {}
    previous = deepcopy(existing)
    existing.update(
        {
            "source_event_key": source_event_key,
            "source_event_kind": f"{payload.get('source_event_name')}:{payload.get('source_event_action')}",
            "pr_number": payload.get("pr_number"),
            "reason": reason,
            "source_event_created_at": payload.get("source_created_at") or payload.get("source_submitted_at"),
            "source_run_id": payload.get("source_run_id"),
            "source_run_attempt": payload.get("source_run_attempt"),
            "source_workflow_file": payload.get("source_workflow_file"),
            "source_artifact_name": payload.get("source_artifact_name"),
            "first_noted_at": existing.get("first_noted_at") or _now_iso(bot),
            "last_checked_at": _now_iso(bot),
            "operator_action_required": True,
            "diagnostic_summary": diagnostic_summary,
            "failure_kind": failure_kind,
        }
    )
    changed = previous != existing
    review_data["deferred_gaps"][source_event_key] = existing
    return changed


def _validate_live_comment_replay_contract(
    bot,
    review_data: dict,
    payload: dict,
    live_body: str,
) -> LiveCommentReplayValidationResult:
    source_comment_class = str(payload.get("comment_class", ""))
    live_classified = classify_comment_payload(bot, live_body)
    live_comment_class = str(live_classified.get("comment_class", ""))
    source_has_non_command_text = bool(payload.get("has_non_command_text"))
    live_has_non_command_text = bool(live_classified.get("has_non_command_text"))

    if live_comment_class != source_comment_class:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} classification changed from "
                f"{source_comment_class} to {live_comment_class}; replay suppressed. "
                f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    if live_has_non_command_text != source_has_non_command_text:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} non-command text classification drifted; "
                f"replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    if source_comment_class in {"command_only", "command_plus_text"} and int(live_classified.get("command_count", 0)) != 1:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} no longer resolves to exactly one command; "
                f"replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    return LiveCommentReplayValidationResult(live_classified, False, False)


def handle_workflow_run_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_workflow_run_event")
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15":
        _log(bot, "info", "V18 workflow_run reconcile safe-noop before epoch flip")
        return False
    payload = _load_deferred_context(bot)
    parsed_payload = parse_deferred_context_payload(payload)
    pr_number = parsed_payload.pr_number
    if pr_number <= 0:
        raise RuntimeError("Deferred context is missing a valid PR number")
    bot.collect_touched_item(pr_number)
    review_data = ensure_review_entry(state, pr_number, create=True)
    if review_data is None:
        raise RuntimeError(f"No review entry available for PR #{pr_number}")
    event_name = parsed_payload.identity.source_event_name
    event_action = parsed_payload.identity.source_event_action
    source_event_key = parsed_payload.identity.source_event_key
    try:
        if isinstance(parsed_payload, ObserverNoopPayload):
            _validate_workflow_run_artifact_identity(bot, parsed_payload.raw_payload)
            _log(
                bot,
                "info",
                f"Observer workflow produced explicit no-op payload for {source_event_key}: {parsed_payload.reason}",
                source_event_key=source_event_key,
                reason=parsed_payload.reason,
            )
            return False

        if event_name == "issue_comment" and isinstance(parsed_payload, DeferredCommentPayload):
            _validate_workflow_run_artifact_identity(bot, parsed_payload.raw_payload)
            context = build_deferred_comment_replay_context(
                parsed_payload,
                expected_event_name="issue_comment",
                live_comment_endpoint=f"issues/comments/{parsed_payload.comment_id}",
            )
            return _reconcile_deferred_comment(
                bot,
                state,
                review_data,
                context,
            )

        if event_name == "pull_request_review_comment" and event_action == "created" and isinstance(parsed_payload, DeferredCommentPayload):
            _validate_workflow_run_artifact_identity(bot, parsed_payload.raw_payload)
            context = build_deferred_comment_replay_context(
                parsed_payload,
                expected_event_name="pull_request_review_comment",
                live_comment_endpoint=f"pulls/comments/{parsed_payload.comment_id}",
            )
            return _reconcile_deferred_comment(
                bot,
                state,
                review_data,
                context,
            )

        if event_name == "pull_request_review" and event_action == "submitted" and isinstance(parsed_payload, DeferredReviewPayload):
            _validate_workflow_run_artifact_identity(bot, parsed_payload.raw_payload)
            context = build_deferred_review_replay_context(
                parsed_payload,
                expected_event_action="submitted",
            )
            review_id = context.review_id
            live_review = _read_optional_reconcile_object(bot, f"pulls/{pr_number}/reviews/{review_id}", label=f"live review #{review_id}")
            _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number}")
            live_commit_id = None
            live_submitted_at = parsed_payload.source_submitted_at
            live_state = parsed_payload.source_review_state
            if isinstance(live_review, dict):
                live_commit_id = live_review.get("commit_id")
                live_submitted_at = live_review.get("submitted_at") or live_submitted_at
                live_state = live_review.get("state") or live_state
            else:
                live_commit_id = parsed_payload.source_commit_id
            actor = context.actor_login
            state_changed = bot.adapters.review_state.maybe_record_head_observation_repair(pr_number, review_data).changed
            if isinstance(review_data.get("current_reviewer"), str) and review_data.get("current_reviewer", "").lower() == actor.lower() and isinstance(live_commit_id, str) and isinstance(live_submitted_at, str):
                accept_channel_event(
                    review_data,
                    "reviewer_review",
                    semantic_key=source_event_key,
                    timestamp=live_submitted_at,
                    actor=actor,
                    reviewed_head_sha=live_commit_id,
                    source_precedence=1,
                )
                record_reviewer_activity(review_data, live_submitted_at)
                state_changed = True
            if _record_review_rebuild(bot, state, pr_number, review_data):
                state_changed = True
            reconciled_changed = _mark_reconciled_source_event(review_data, source_event_key)
            gap_cleared_changed = _clear_source_event_key(review_data, source_event_key)
            return state_changed or reconciled_changed or gap_cleared_changed

        if event_name == "pull_request_review" and event_action == "dismissed" and isinstance(parsed_payload, DeferredReviewPayload):
            _validate_workflow_run_artifact_identity(bot, parsed_payload.raw_payload)
            context = build_deferred_review_replay_context(
                parsed_payload,
                expected_event_action="dismissed",
            )
            accept_channel_event(
                review_data,
                "review_dismissal",
                semantic_key=source_event_key,
                timestamp=_now_iso(bot),
                dismissal_only=True,
            )
            state_changed = bot.adapters.review_state.maybe_record_head_observation_repair(pr_number, review_data).changed
            if _record_review_rebuild(bot, state, pr_number, review_data):
                state_changed = True
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return True
    except RuntimeError as exc:
        failure_kind = exc.failure_kind if isinstance(exc, ReconcileReadError) else None
        gap_changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
            failure_kind=failure_kind,
        )
        if gap_changed:
            return True
        raise
    raise RuntimeError("Unsupported deferred workflow_run payload")
