"""Top-level reviewer-bot orchestration."""

import sys

from .context import (
    AppEventContextRuntime,
    AppExecutionRuntime,
    EventContext,
    ExecutionResult,
)
from .event_inputs import build_event_context as decode_event_context
from .maintenance import (
    collect_status_projection_repair_items,
    status_projection_repair_needed,
)


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
        marker = {
            "kind": "projection_failure",
            "reason": reason,
            "recorded_at": bot.datetime.now(bot.timezone.utc).isoformat(),
        }
        existing = review_data.get("repair_needed")
        if isinstance(existing, dict) and {
            key: value for key, value in existing.items() if key != "recorded_at"
        } == {
            key: value for key, value in marker.items() if key != "recorded_at"
        }:
            continue
        review_data["repair_needed"] = marker
        changed = True
    return changed


def build_event_context(bot: AppEventContextRuntime) -> EventContext:
    return decode_event_context(bot)


def _classify_event_intent_from_context(bot: AppEventContextRuntime, context: EventContext) -> str:
    event_name = context.event_name
    event_action = context.event_action

    if event_name in {"issues", "pull_request_target"}:
        if event_action in {"opened", "labeled", "edited", "closed", "synchronize"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "issue_comment":
        if event_action == "created":
            if context.is_pull_request is True:
                trust_class = bot.get_config_value("REVIEWER_BOT_TRUST_CLASS").strip()
                if trust_class in {"pr_deferred_reconcile", "safe_noop"}:
                    return bot.EVENT_INTENT_NON_MUTATING_DEFER
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_review":
        if event_action in {"submitted", "dismissed"}:
            return bot.EVENT_INTENT_NON_MUTATING_DEFER
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_review_comment":
        if event_action == "created":
            return bot.EVENT_INTENT_NON_MUTATING_DEFER
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_run":
        if event_action != "completed":
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        if context.workflow_run_event in {"pull_request_review", "issue_comment", "pull_request_review_comment"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_dispatch":
        if context.manual_action in {"show-state", "preview-reviewer-board"}:
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
        workflow_run_event=context.workflow_run_event,
        workflow_run_event_action=context.workflow_run_event_action,
        workflow_run_head_sha=context.workflow_run_head_sha,
        workflow_run_reconcile_pr_number=context.workflow_run_reconcile_pr_number,
        workflow_run_reconcile_head_sha=context.workflow_run_reconcile_head_sha,
        workflow_run_id=context.workflow_run_id,
        workflow_name=context.workflow_name,
        workflow_job_name=context.workflow_job_name,
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

    lock_acquired = False
    release_failed = False
    exit_code = 0

    state_changed = False
    status_labels_changed = False
    sync_changes: list[str] = []
    restored: list[str] = []
    loaded_active_reviews_count = 0
    touched_items: list[int] = []
    projection_failure: RuntimeError | None = None
    loaded_epoch: str | None = None
    projection_epoch_repair = False

    try:
        if lock_required:
            bot.locks.acquire()
            lock_acquired = True

        state = bot.state_store.load_state(fail_on_unavailable=lock_required)
        active_reviews = state.get("active_reviews")
        if isinstance(active_reviews, dict):
            loaded_active_reviews_count = len(active_reviews)
        loaded_epoch = state.get("freshness_runtime_epoch") if isinstance(state.get("freshness_runtime_epoch"), str) else None

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
            elif event_action == "labeled":
                state_changed = bot.handlers.handle_labeled_event(state)
            elif event_action == "edited":
                state_changed = bot.handlers.handle_issue_edited_event(state)
            elif event_action == "closed":
                state_changed = bot.handlers.handle_closed_event(state)

        elif event_name == "pull_request_target":
            if event_action == "opened":
                state_changed = bot.handlers.handle_issue_or_pr_opened(state)
            elif event_action == "labeled":
                state_changed = bot.handlers.handle_labeled_event(state)
            elif event_action == "closed":
                state_changed = bot.handlers.handle_closed_event(state)
            elif event_action == "synchronize":
                state_changed = bot.handlers.handle_pull_request_target_synchronize(state)

        elif event_name == "pull_request_review":
            if event_action in {"submitted", "dismissed"}:
                state_changed = bot.handlers.handle_pull_request_review_event(state)

        elif event_name == "issue_comment":
            if event_action == "created":
                state_changed = bot.handlers.handle_comment_event(state)

        elif event_name == "workflow_dispatch":
            state_changed = bot.handlers.handle_manual_dispatch(state)

        elif event_name == "schedule":
            state_changed = bot.handlers.handle_scheduled_check(state)

        elif event_name == "workflow_run":
            if event_action == "completed":
                if context.workflow_run_event in {"pull_request_review", "issue_comment", "pull_request_review_comment"}:
                    state_changed = bot.handlers.handle_workflow_run_event(state)
                else:
                    _log(
                        bot,
                        "info",
                        f"Ignoring workflow_run event with unsupported source event: {context.workflow_run_event or '<missing>'}",
                        workflow_run_event=context.workflow_run_event or "<missing>",
                    )

        touched_items = bot.drain_touched_items()
        if lock_required and event_name in {"schedule", "workflow_dispatch"} and status_projection_repair_needed(bot, state):
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

            if event_name == "schedule":
                current_active_reviews = state.get("active_reviews")
                current_active_reviews_count = (
                    len(current_active_reviews) if isinstance(current_active_reviews, dict) else 0
                )
                allow_empty_override = (
                    bot.get_config_value("ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE").strip().lower() == "true"
                )
                if (
                    loaded_active_reviews_count > 0
                    and current_active_reviews_count == 0
                    and not allow_empty_override
                ):
                    raise RuntimeError(
                        "STATE_GUARD_BLOCKED_EMPTY_ACTIVE_REVIEWS: refusing to persist schedule "
                        f"state update that drops active_reviews from {loaded_active_reviews_count} "
                        "to 0. Set ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE=true to override."
                    )

            _log(bot, "info", "State updates detected; attempting to persist reviewer-bot state.")
            _revalidate_epoch(bot, loaded_epoch, "authoritative save")
            if not bot.state_store.save_state(state):
                raise RuntimeError(
                    "State updates were computed but could not be persisted. "
                    "Failing this run to avoid silent success."
                )

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
