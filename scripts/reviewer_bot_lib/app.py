"""Top-level reviewer-bot orchestration."""

import os
import sys

from .context import ReviewerBotContext
from .maintenance import (
    collect_status_projection_repair_items,
    status_projection_repair_needed,
)


def _revalidate_epoch(bot: ReviewerBotContext, expected_epoch: str | None, phase: str) -> None:
    if expected_epoch is None:
        return
    latest_state = bot.load_state(fail_on_unavailable=True)
    latest_epoch = latest_state.get("freshness_runtime_epoch")
    if latest_epoch != expected_epoch:
        raise RuntimeError(
            f"Epoch changed from {expected_epoch} to {latest_epoch} before {phase}; failing closed."
        )


def _mark_projection_repair_needed(bot: ReviewerBotContext, state: dict, issue_numbers: list[int], reason: str) -> bool:
    changed = False
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    for issue_number in issue_numbers:
        review_data = active_reviews.get(str(issue_number))
        if not isinstance(review_data, dict):
            continue
        review_data["repair_needed"] = {
            "kind": "projection_failure",
            "reason": reason,
            "recorded_at": bot.datetime.now(bot.timezone.utc).isoformat(),
        }
        changed = True
    return changed


def classify_event_intent(bot: ReviewerBotContext, event_name: str, event_action: str) -> str:
    """Classify whether a run can mutate reviewer-bot state."""
    if event_name in {"issues", "pull_request_target"}:
        if event_action in {"opened", "labeled", "edited", "closed", "synchronize"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "issue_comment":
        if event_action == "created":
            if os.environ.get("IS_PULL_REQUEST", "false").lower() == "true":
                trust_class = os.environ.get("REVIEWER_BOT_TRUST_CLASS", "").strip()
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
        workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
        if workflow_run_event in {"pull_request_review", "issue_comment", "pull_request_review_comment"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_dispatch":
        action = os.environ.get("MANUAL_ACTION", "").strip()
        if action == "show-state":
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        return bot.EVENT_INTENT_MUTATING

    if event_name == "schedule":
        return bot.EVENT_INTENT_MUTATING

    return bot.EVENT_INTENT_NON_MUTATING_READONLY


def event_requires_lease_lock(bot: ReviewerBotContext, event_name: str, event_action: str) -> bool:
    """Backwards-compatible helper for tests and call sites."""
    return classify_event_intent(bot, event_name, event_action) == bot.EVENT_INTENT_MUTATING


def main(bot: ReviewerBotContext):
    """Main entry point for the reviewer bot."""
    event_name = os.environ.get("EVENT_NAME", "")
    event_action = os.environ.get("EVENT_ACTION", "")
    bot.drain_touched_items()

    event_intent = classify_event_intent(bot, event_name, event_action)
    lock_required = event_intent == bot.EVENT_INTENT_MUTATING
    print(
        f"Event: {event_name}, Action: {event_action}, Intent: {event_intent}, "
        f"Lock Required: {lock_required}"
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
            bot.acquire_state_issue_lease_lock()
            lock_acquired = True

        state = bot.load_state(fail_on_unavailable=lock_required)
        active_reviews = state.get("active_reviews")
        if isinstance(active_reviews, dict):
            loaded_active_reviews_count = len(active_reviews)
        loaded_epoch = state.get("freshness_runtime_epoch") if isinstance(state.get("freshness_runtime_epoch"), str) else None

        if lock_required:
            state, restored = bot.process_pass_until_expirations(state)
            if restored:
                print(f"Restored from pass-until: {restored}")

            state, sync_changes = bot.sync_members_with_queue(state)
            if sync_changes:
                print(f"Members sync changes: {sync_changes}")

        if event_name == "issues":
            if event_action == "opened":
                state_changed = bot.handle_issue_or_pr_opened(state)
            elif event_action == "labeled":
                state_changed = bot.handle_labeled_event(state)
            elif event_action == "edited":
                state_changed = bot.handle_issue_edited_event(state)
            elif event_action == "closed":
                state_changed = bot.handle_closed_event(state)

        elif event_name == "pull_request_target":
            if event_action == "opened":
                state_changed = bot.handle_issue_or_pr_opened(state)
            elif event_action == "labeled":
                state_changed = bot.handle_labeled_event(state)
            elif event_action == "closed":
                state_changed = bot.handle_closed_event(state)
            elif event_action == "synchronize":
                state_changed = bot.handle_pull_request_target_synchronize(state)

        elif event_name == "pull_request_review":
            if event_action in {"submitted", "dismissed"}:
                state_changed = bot.handle_pull_request_review_event(state)

        elif event_name == "issue_comment":
            if event_action == "created":
                state_changed = bot.handle_comment_event(state)

        elif event_name == "workflow_dispatch":
            state_changed = bot.handle_manual_dispatch(state)

        elif event_name == "schedule":
            state_changed = bot.handle_scheduled_check(state)

        elif event_name == "workflow_run":
            if event_action == "completed":
                if os.environ.get("WORKFLOW_RUN_EVENT", "").strip() in {"pull_request_review", "issue_comment", "pull_request_review_comment"}:
                    state_changed = bot.handle_workflow_run_event(state)
                else:
                    print(
                        "Ignoring workflow_run event with unsupported source event: "
                        f"{os.environ.get('WORKFLOW_RUN_EVENT', '').strip() or '<missing>'}"
                    )

        touched_items = bot.drain_touched_items()
        if event_name in {"schedule", "workflow_dispatch"} and status_projection_repair_needed(bot, state):
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
                    os.environ.get("ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE", "").strip().lower() == "true"
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

            print("State updates detected; attempting to persist reviewer-bot state.")
            _revalidate_epoch(bot, loaded_epoch, "authoritative save")
            if not bot.save_state(state):
                raise RuntimeError(
                    "State updates were computed but could not be persisted. "
                    "Failing this run to avoid silent success."
                )

            if touched_items:
                state = bot.load_state(fail_on_unavailable=True)

        if touched_items:
            if not lock_acquired:
                raise RuntimeError(
                    "Status-label projection reached apply path without lease lock. "
                    "Acquire lock before mutating labels."
                )
            _revalidate_epoch(bot, loaded_epoch, "status-label projection")
            try:
                status_labels_changed = bot.sync_status_labels_for_items(state, touched_items)
            except RuntimeError as exc:
                projection_failure = exc
                print(
                    f"WARNING: Authoritative state is persisted but status-label projection failed: {exc}",
                    file=sys.stderr,
                )
                if _mark_projection_repair_needed(bot, state, touched_items, str(exc)):
                    _revalidate_epoch(bot, loaded_epoch, "projection-failure repair marker save")
                    if not bot.save_state(state):
                        raise RuntimeError(
                            "Projection failed and repair-needed metadata could not be persisted."
                        )
            else:
                if projection_epoch_repair:
                    state["status_projection_epoch"] = bot.STATUS_PROJECTION_EPOCH
                    _revalidate_epoch(bot, loaded_epoch, "status-projection epoch save")
                    if not bot.save_state(state):
                        raise RuntimeError(
                            "Status projection epoch repair succeeded but could not be persisted."
                        )

        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as output_file:
            output_file.write(
                "state_changed=true\n"
                if (state_changed or bool(sync_changes) or bool(restored) or status_labels_changed)
                else "state_changed=false\n"
            )
        if projection_failure is not None:
            print(
                "PROJECTION_REPAIR_REQUIRED: labels remain unchanged until a trusted repair path succeeds.",
                file=sys.stderr,
            )

    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = 1
    except Exception as exc:  # pragma: no cover - defensive hard-fail path
        print(f"ERROR: Unexpected reviewer-bot failure: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if lock_acquired:
            if not bot.release_state_issue_lease_lock():
                release_failed = True

    if release_failed:
        print(
            "ERROR: Failed to release reviewer-bot lease lock after processing event.",
            file=sys.stderr,
        )
        exit_code = 1

    if exit_code:
        sys.exit(exit_code)
