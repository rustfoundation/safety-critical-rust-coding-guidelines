"""Top-level reviewer-bot orchestration."""

import hashlib
import json
import sys
from dataclasses import dataclass

from . import maintenance, reconcile
from .context import EventContext, ExecutionResult, ManualDispatchRequest
from .event_inputs import build_event_context as decode_event_context
from .maintenance import (
    collect_status_projection_repair_items,
    status_projection_repair_needed,
)
from .repair_records import projection_repair_marker, store_repair_marker
from .runtime_protocols import AppEventContextRuntime, AppExecutionRuntime


@dataclass(frozen=True)
class StateIssueWriteReceipt:
    issue_number: int | None
    mutation_kind: str
    issue_body_hash_before: str | None
    issue_body_hash_after: str | None
    external_side_effects_recorded: tuple[str, ...]
    state_save_attempted: bool
    state_save_succeeded: bool
    write_status: str
    failure_kind: str | None
    next_recovery_action: str | None
    recorded_at: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "mutation_kind": self.mutation_kind,
            "issue_body_hash_before": self.issue_body_hash_before,
            "issue_body_hash_after": self.issue_body_hash_after,
            "external_side_effects_recorded": sorted(self.external_side_effects_recorded),
            "state_save_attempted": self.state_save_attempted,
            "state_save_succeeded": self.state_save_succeeded,
            "write_status": self.write_status,
            "failure_kind": self.failure_kind,
            "next_recovery_action": self.next_recovery_action,
            "recorded_at": self.recorded_at,
        }


def build_state_issue_write_receipt(
    *,
    issue_number: int | None,
    mutation_kind: str,
    issue_body_hash_before: str | None,
    issue_body_hash_after: str | None,
    external_side_effects_recorded: tuple[str, ...],
    state_save_attempted: bool,
    state_save_succeeded: bool,
    failure_kind: str | None = None,
    recorded_at: str | None = None,
) -> StateIssueWriteReceipt:
    if not state_save_attempted:
        write_status = "not_attempted_read_only" if mutation_kind.endswith("preview") else "not_attempted_no_state_change"
        recovery = "none"
    elif state_save_succeeded:
        write_status = "persisted"
        recovery = "none"
    elif external_side_effects_recorded:
        write_status = "failed_after_external_side_effect"
        recovery = (
            "recover_from_live_github_receipt"
            if any("comment" in item for item in external_side_effects_recorded)
            else "retry_state_save_before_replay_closeout"
        )
    else:
        write_status = "failed_before_external_side_effect"
        recovery = "retry_state_save_before_replay_closeout"
    return StateIssueWriteReceipt(
        issue_number=issue_number,
        mutation_kind=mutation_kind,
        issue_body_hash_before=issue_body_hash_before,
        issue_body_hash_after=issue_body_hash_after,
        external_side_effects_recorded=external_side_effects_recorded,
        state_save_attempted=state_save_attempted,
        state_save_succeeded=state_save_succeeded,
        write_status=write_status,
        failure_kind=failure_kind,
        next_recovery_action=recovery,
        recorded_at=recorded_at,
    )


def record_state_issue_write_receipt(
    bot,
    *,
    issue_number: int | None,
    mutation_kind: str,
    issue_body_hash_before: str | None,
    issue_body_hash_after: str | None,
    external_side_effects_recorded: tuple[str, ...],
    state_save_attempted: bool,
    state_save_succeeded: bool,
    failure_kind: str | None = None,
) -> StateIssueWriteReceipt:
    receipt = build_state_issue_write_receipt(
        issue_number=issue_number,
        mutation_kind=mutation_kind,
        issue_body_hash_before=issue_body_hash_before,
        issue_body_hash_after=issue_body_hash_after,
        external_side_effects_recorded=external_side_effects_recorded,
        state_save_attempted=state_save_attempted,
        state_save_succeeded=state_save_succeeded,
        failure_kind=failure_kind,
        recorded_at=bot.datetime.now(bot.timezone.utc).isoformat() if hasattr(bot, "datetime") else None,
    )
    if hasattr(bot, "logger"):
        bot.logger.event("info", "state issue write receipt", **receipt.to_output())
    return receipt


def _store_state_issue_write_receipt(state: dict, receipt: StateIssueWriteReceipt) -> bool:
    receipts = state.setdefault("state_issue_write_receipts", {})
    if not isinstance(receipts, dict):
        receipts = {}
        state["state_issue_write_receipts"] = receipts
    key = f"{receipt.mutation_kind}:{receipt.issue_number or 'global'}:{receipt.recorded_at or 'pending'}"
    receipts[key] = receipt.to_output()
    return True


def _stable_state_hash(state: dict | None) -> str | None:
    if not isinstance(state, dict):
        return None
    try:
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _primary_issue_number(context: EventContext, touched_items: list[int]) -> int | None:
    if isinstance(context.issue_number, int) and context.issue_number > 0:
        return context.issue_number
    if len(touched_items) == 1:
        return touched_items[0]
    return None


def _external_side_effects_for_save(
    *,
    context: EventContext,
    state_changed: bool,
    sync_changes: list[str],
    restored: list[str],
    schedule_result: reconcile.WorkflowRunHandlerResult | maintenance.ScheduleHandlerResult | None,
    workflow_run_result: reconcile.WorkflowRunHandlerResult | None,
) -> tuple[str, ...]:
    effects: list[str] = []
    if sync_changes:
        effects.append("member_sync")
    if restored:
        effects.append("pass_until_restore")
    if state_changed:
        if context.event_name == "issue_comment":
            effects.append("comment_command_or_freshness")
        elif context.event_name == "workflow_run" and workflow_run_result is not None:
            effects.append("workflow_replay")
        elif schedule_result is not None:
            effects.append("scheduled_maintenance_or_reminder")
        else:
            effects.append(f"{context.event_name}:{context.event_action or 'none'}")
    return tuple(dict.fromkeys(effects))


def _log(bot: AppExecutionRuntime, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _revalidate_epoch(bot: AppExecutionRuntime, expected_epoch: str | None, phase: str) -> None:
    if expected_epoch is None:
        return
    latest_state = bot.state_store.load_state(fail_on_unavailable=True)
    latest_epoch = latest_state.get("freshness_runtime_epoch")
    if latest_epoch != expected_epoch:
        raise RuntimeError(
            f"Epoch changed from {expected_epoch} to {latest_epoch} before {phase}; failing closed."
        )


def _mark_projection_repair_needed(bot: AppExecutionRuntime, state: dict, issue_numbers: list[int], reason: str) -> bool:
    changed = False
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    for issue_number in issue_numbers:
        review_data = active_reviews.get(str(issue_number))
        if not isinstance(review_data, dict):
            continue
        marker = projection_repair_marker(reason, bot.datetime.now(bot.timezone.utc).isoformat())
        changed = store_repair_marker(review_data, "status_label_projection", marker) or changed
    return changed


def build_event_context(bot: AppEventContextRuntime) -> EventContext:
    return decode_event_context(bot)


def _classify_event_intent_from_context(bot: AppEventContextRuntime, context: EventContext) -> str:
    event_name = context.event_name
    event_action = context.event_action

    if event_name == "issues":
        if event_action in {
            "opened",
            "edited",
            "labeled",
            "unlabeled",
            "assigned",
            "unassigned",
            "reopened",
            "closed",
        }:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_target":
        if event_action in {"opened", "labeled", "unlabeled", "reopened", "closed", "synchronize"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "issue_comment":
        if event_action == "created":
            if context.is_pull_request is True:
                route_outcome = bot.get_config_value("REVIEWER_BOT_ROUTE_OUTCOME").strip()
                if route_outcome in {"deferred_reconcile", "safe_noop"}:
                    return bot.EVENT_INTENT_NON_MUTATING_DEFER
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_review_comment":
        if event_action == "created":
            return bot.EVENT_INTENT_NON_MUTATING_DEFER
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_run":
        if event_action != "completed":
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        if context.workflow_kind == "reconcile":
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_dispatch":
        if context.manual_action in {
            "show-state",
            "preview-check-overdue",
            "preview-status-label-projection",
            "preview-issue314-state-health",
            "preview-reviewer-board",
        }:
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        return bot.EVENT_INTENT_MUTATING

    if event_name == "schedule":
        return bot.EVENT_INTENT_MUTATING

    return bot.EVENT_INTENT_NON_MUTATING_READONLY


def classify_event_intent(bot: AppEventContextRuntime, event_name: str, event_action: str) -> str:
    """Classify whether a run can mutate reviewer-bot state."""
    context = build_event_context(bot)
    context = EventContext(
        event_name=event_name,
        event_action=event_action,
        issue_number=context.issue_number,
        is_pull_request=context.is_pull_request,
        issue_author=context.issue_author,
        issue_state=context.issue_state,
        issue_labels=context.issue_labels,
        comment_id=context.comment_id,
        comment_author=context.comment_author,
        comment_body=context.comment_body,
        comment_source_event_key=context.comment_source_event_key,
        pr_is_cross_repository=context.pr_is_cross_repository,
        review_author=context.review_author,
        review_state=context.review_state,
        workflow_kind=context.workflow_kind,
        workflow_run_triggering_conclusion=context.workflow_run_triggering_conclusion,
        workflow_artifact_contract=context.workflow_artifact_contract,
        manual_action=context.manual_action,
    )
    return _classify_event_intent_from_context(bot, context)


def event_requires_lease_lock(bot: AppEventContextRuntime, event_name: str, event_action: str) -> bool:
    """Backwards-compatible helper for tests and call sites."""
    return classify_event_intent(bot, event_name, event_action) == bot.EVENT_INTENT_MUTATING


def execute_run(bot: AppExecutionRuntime, context: EventContext) -> ExecutionResult:
    bot.drain_touched_items()

    event_name = context.event_name
    event_action = context.event_action
    event_intent = _classify_event_intent_from_context(bot, context)
    workflow_run_missing_optional_payload = False
    lock_required = False

    lock_acquired = False
    release_failed = False
    exit_code = 0

    state_changed = False
    status_labels_changed = False
    sync_changes: list[str] = []
    restored: list[str] = []
    loaded_active_reviews_count = 0
    loaded_active_review_numbers: set[int] = set()
    touched_items: list[int] = []
    projection_failure: RuntimeError | None = None
    loaded_epoch: str | None = None
    projection_epoch_repair = False
    workflow_run_result: reconcile.WorkflowRunHandlerResult | None = None
    schedule_result: maintenance.ScheduleHandlerResult | None = None
    loaded_state_hash: str | None = None
    manual_projection_policy: maintenance.ManualDispatchProjectionPolicy | None = None

    try:
        if (
            event_name == "workflow_run"
            and event_action == "completed"
            and context.workflow_kind == "reconcile"
            and reconcile.optional_router_payload_missing(bot, context)
        ):
            workflow_run_missing_optional_payload = True
            event_intent = bot.EVENT_INTENT_NON_MUTATING_READONLY
        lock_required = event_intent == bot.EVENT_INTENT_MUTATING
        _log(
            bot,
            "info",
            f"Event: {event_name}, Action: {event_action}, Intent: {event_intent}, Lock Required: {lock_required}",
            event_name=event_name,
            event_action=event_action,
            event_intent=event_intent,
            lock_required=lock_required,
        )

        if lock_required:
            bot.locks.acquire()
            lock_acquired = True

        state = bot.state_store.load_state(fail_on_unavailable=lock_required)
        loaded_state_hash = _stable_state_hash(state)
        active_reviews = state.get("active_reviews")
        if isinstance(active_reviews, dict):
            loaded_active_reviews_count = len(active_reviews)
            loaded_active_review_numbers = {
                int(issue_key)
                for issue_key in active_reviews
                if isinstance(issue_key, str) and issue_key.isdigit()
            }
        loaded_epoch = state.get("freshness_runtime_epoch") if isinstance(state.get("freshness_runtime_epoch"), str) else None
        if event_name == "workflow_dispatch":
            manual_projection_policy = maintenance.derive_manual_dispatch_projection_policy(
                ManualDispatchRequest(
                    action=context.manual_action or "",
                    issue_number=context.issue_number,
                )
            )

        if lock_required:
            state, restored = bot.adapters.workflow.process_pass_until_expirations(state)
            if restored:
                _log(bot, "info", f"Restored from pass-until: {restored}", restored=restored)

            state, sync_changes = bot.adapters.workflow.sync_members_with_queue(state)
            if sync_changes:
                _log(bot, "info", f"Members sync changes: {sync_changes}", sync_changes=sync_changes)

        if event_name == "issues":
            if event_action == "opened":
                state_changed = bot.handlers.handle_issue_or_pr_opened(state)
            elif event_action == "assigned":
                state_changed = bot.handlers.handle_assigned_event(state)
            elif event_action == "unassigned":
                state_changed = bot.handlers.handle_unassigned_event(state)
            elif event_action == "labeled":
                state_changed = bot.handlers.handle_labeled_event(state)
            elif event_action == "unlabeled":
                state_changed = bot.handlers.handle_unlabeled_event(state)
            elif event_action == "edited":
                state_changed = bot.handlers.handle_issue_edited_event(state)
            elif event_action == "reopened":
                state_changed = bot.handlers.handle_reopened_event(state)
            elif event_action == "closed":
                state_changed = bot.handlers.handle_closed_event(state)

        elif event_name == "pull_request_target":
            if event_action == "opened":
                state_changed = bot.handlers.handle_issue_or_pr_opened(state)
            elif event_action == "labeled":
                state_changed = bot.handlers.handle_labeled_event(state)
            elif event_action == "unlabeled":
                state_changed = bot.handlers.handle_unlabeled_event(state)
            elif event_action == "reopened":
                state_changed = bot.handlers.handle_reopened_event(state)
            elif event_action == "closed":
                state_changed = bot.handlers.handle_closed_event(state)
            elif event_action == "synchronize":
                state_changed = bot.handlers.handle_pull_request_target_synchronize(state)

        elif event_name == "issue_comment":
            if event_action == "created":
                if event_intent == bot.EVENT_INTENT_NON_MUTATING_DEFER:
                    _log(
                        bot,
                        "info",
                        "Skipping direct PR issue-comment mutation for deferred router outcome.",
                    )
                else:
                    state_changed = bot.handlers.handle_comment_event(state)

        elif event_name == "workflow_dispatch":
            if maintenance.is_schedule_like_manual_action(context.manual_action):
                schedule_result = bot.handlers.handle_manual_dispatch_result(state)
                state_changed = schedule_result.state_changed
            else:
                state_changed = bot.handlers.handle_manual_dispatch(state)

        elif event_name == "schedule":
            schedule_result = bot.handlers.handle_scheduled_check_result(state)
            state_changed = schedule_result.state_changed

        elif event_name == "workflow_run":
            if event_action == "completed":
                if workflow_run_missing_optional_payload:
                    _log(
                        bot,
                        "info",
                        "Skipping successful router workflow_run with no deferred artifact.",
                    )
                elif context.workflow_kind == "reconcile":
                    workflow_run_result = reconcile.handle_workflow_run_event_result(bot, state)
                    state_changed = workflow_run_result.state_changed
                else:
                    _log(
                        bot,
                        "info",
                        "Ignoring workflow_run event outside retained reconcile envelope.",
                        workflow_kind=context.workflow_kind or "<missing>",
                        workflow_conclusion=context.workflow_run_triggering_conclusion or "<missing>",
                    )

        if workflow_run_result is not None:
            touched_items = workflow_run_result.touched_items
        elif schedule_result is not None:
            touched_items = schedule_result.touched_items
        else:
            touched_items = bot.drain_touched_items()
        allow_epoch_repair_expansion = (
            manual_projection_policy.allow_epoch_repair_expansion
            if manual_projection_policy is not None
            else True
        )
        if (
            lock_required
            and event_name in {"schedule", "workflow_dispatch"}
            and allow_epoch_repair_expansion
            and status_projection_repair_needed(bot, state)
        ):
            touched_items = sorted(
                {
                    *touched_items,
                    *collect_status_projection_repair_items(bot, state),
                }
            )
            projection_epoch_repair = True

        if state_changed or sync_changes or restored:
            if not lock_acquired:
                raise RuntimeError(
                    "State mutation reached save path without lease lock. "
                    "Acquire lock before mutating state."
                )

            if schedule_result is not None:
                current_active_reviews = state.get("active_reviews")
                current_active_reviews_count = (
                    len(current_active_reviews) if isinstance(current_active_reviews, dict) else 0
                )
                allow_empty_override = (
                    bot.get_config_value("ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE").strip().lower() == "true"
                )
                allow_closed_cleanup_empty = (
                    schedule_result is not None
                    and loaded_active_reviews_count == len(loaded_active_review_numbers)
                    and bool(loaded_active_review_numbers)
                    and set(schedule_result.closed_cleanup_removed_items) == loaded_active_review_numbers
                )
                if (
                    loaded_active_reviews_count > 0
                    and current_active_reviews_count == 0
                    and not allow_empty_override
                    and not allow_closed_cleanup_empty
                ):
                    raise RuntimeError(
                        "STATE_GUARD_BLOCKED_EMPTY_ACTIVE_REVIEWS: refusing to persist maintenance "
                        f"state update that drops active_reviews from {loaded_active_reviews_count} "
                        "to 0. Set ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE=true to override."
                    )

            _log(bot, "info", "State updates detected; attempting to persist reviewer-bot state.")
            _revalidate_epoch(bot, loaded_epoch, "authoritative save")
            save_side_effects = _external_side_effects_for_save(
                context=context,
                state_changed=state_changed,
                sync_changes=sync_changes,
                restored=restored,
                schedule_result=schedule_result,
                workflow_run_result=workflow_run_result,
            )
            state_hash_after = _stable_state_hash(state)
            success_receipt = build_state_issue_write_receipt(
                issue_number=_primary_issue_number(context, touched_items),
                mutation_kind=f"{event_name}:{event_action or context.manual_action or 'none'}",
                issue_body_hash_before=loaded_state_hash,
                issue_body_hash_after=state_hash_after,
                external_side_effects_recorded=save_side_effects,
                state_save_attempted=True,
                state_save_succeeded=True,
                recorded_at=bot.datetime.now(bot.timezone.utc).isoformat(),
            )
            _store_state_issue_write_receipt(state, success_receipt)
            if not bot.state_store.save_state(state):
                failure_receipt = record_state_issue_write_receipt(
                    bot,
                    issue_number=_primary_issue_number(context, touched_items),
                    mutation_kind=f"{event_name}:{event_action or context.manual_action or 'none'}",
                    issue_body_hash_before=loaded_state_hash,
                    issue_body_hash_after=state_hash_after,
                    external_side_effects_recorded=save_side_effects,
                    state_save_attempted=True,
                    state_save_succeeded=False,
                    failure_kind="state_save_failed",
                )
                _store_state_issue_write_receipt(state, failure_receipt)
                if bot.state_store.save_state(state):
                    raise RuntimeError(
                        "State save initially failed after external side effects; "
                        "a recovery receipt was persisted for the next run."
                    )
                raise RuntimeError(
                    "State updates were computed but could not be persisted. "
                    "Failing this run to avoid silent success."
                )
            if hasattr(bot, "logger"):
                bot.logger.event("info", "state issue write receipt", **success_receipt.to_output())

            if touched_items:
                state = bot.state_store.load_state(fail_on_unavailable=True)

        if touched_items:
            if not lock_acquired:
                raise RuntimeError(
                    "Status-label projection reached apply path without lease lock. "
                    "Acquire lock before mutating labels."
                )
            _revalidate_epoch(bot, loaded_epoch, "status-label projection")
            try:
                status_labels_changed = bot.adapters.workflow.sync_status_labels_for_items(state, touched_items)
            except RuntimeError as exc:
                projection_failure = exc
                _log(
                    bot,
                    "warning",
                    f"Authoritative state is persisted but status-label projection failed: {exc}",
                    projection_error=str(exc),
                )
                if _mark_projection_repair_needed(bot, state, touched_items, str(exc)):
                    _revalidate_epoch(bot, loaded_epoch, "projection-failure repair marker save")
                    if not bot.state_store.save_state(state):
                        raise RuntimeError(
                            "Projection failed and repair-needed metadata could not be persisted."
                        )
            else:
                if projection_epoch_repair:
                    state["status_projection_epoch"] = bot.STATUS_PROJECTION_EPOCH
                    _revalidate_epoch(bot, loaded_epoch, "status-projection epoch save")
                    if not bot.state_store.save_state(state):
                        raise RuntimeError(
                            "Status projection epoch repair succeeded but could not be persisted."
                        )

        execution_state_changed = bool(state_changed or sync_changes or restored or status_labels_changed)

        bot.write_output(
            "state_changed",
            "true" if execution_state_changed else "false",
        )
        if projection_failure is not None:
            _log(
                bot,
                "warning",
                "PROJECTION_REPAIR_REQUIRED: labels remain unchanged until a trusted repair path succeeds.",
            )

    except RuntimeError as exc:
        _log(bot, "error", f"ERROR: {exc}", error=str(exc))
        exit_code = 1
    except Exception as exc:  # pragma: no cover - defensive hard-fail path
        _log(bot, "error", f"ERROR: Unexpected reviewer-bot failure: {exc}", error=str(exc))
        exit_code = 1
    finally:
        if lock_acquired:
            if not bot.locks.release():
                release_failed = True

    if release_failed:
        _log(bot, "error", "ERROR: Failed to release reviewer-bot lease lock after processing event.")
        exit_code = 1

    return ExecutionResult(
        exit_code=exit_code,
        state_changed=bool(state_changed or sync_changes or restored or status_labels_changed),
        release_failed=release_failed,
    )


def main(bot: AppExecutionRuntime):
    """Main entry point for the reviewer bot."""
    result = execute_run(bot, build_event_context(bot))
    if result.exit_code:
        sys.exit(result.exit_code)
