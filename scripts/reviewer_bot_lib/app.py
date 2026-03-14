"""Top-level reviewer-bot orchestration."""

import os
import sys


def classify_event_intent(bot, event_name: str, event_action: str) -> str:
    """Classify whether a run can mutate reviewer-bot state."""
    if event_name in {"issues", "pull_request_target"}:
        if event_action in {"opened", "labeled", "closed"}:
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "issue_comment":
        if event_action == "created":
            return bot.EVENT_INTENT_MUTATING
        return bot.EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_review":
        if event_action not in {"submitted", "dismissed"}:
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        is_cross_repo = os.environ.get("PR_IS_CROSS_REPOSITORY", "false").lower() == "true"
        if is_cross_repo:
            return bot.EVENT_INTENT_NON_MUTATING_DEFER
        return bot.EVENT_INTENT_MUTATING

    if event_name == "workflow_run":
        if event_action != "completed":
            return bot.EVENT_INTENT_NON_MUTATING_READONLY
        workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
        workflow_run_event_action = os.environ.get("WORKFLOW_RUN_EVENT_ACTION", "").strip().lower()
        if (
            workflow_run_event == "pull_request_review"
            and workflow_run_event_action in {"submitted", "dismissed"}
        ):
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


def event_requires_lease_lock(bot, event_name: str, event_action: str) -> bool:
    """Backwards-compatible helper for tests and call sites."""
    return classify_event_intent(bot, event_name, event_action) == bot.EVENT_INTENT_MUTATING


def main(bot):
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

    try:
        if lock_required:
            bot.acquire_state_issue_lease_lock()
            lock_acquired = True

        state = bot.load_state(fail_on_unavailable=lock_required)
        active_reviews = state.get("active_reviews")
        if isinstance(active_reviews, dict):
            loaded_active_reviews_count = len(active_reviews)

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
            elif event_action == "closed":
                state_changed = bot.handle_closed_event(state)

        elif event_name == "pull_request_target":
            if event_action == "opened":
                state_changed = bot.handle_issue_or_pr_opened(state)
            elif event_action == "labeled":
                state_changed = bot.handle_labeled_event(state)
            elif event_action == "closed":
                state_changed = bot.handle_closed_event(state)

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
                if os.environ.get("WORKFLOW_RUN_EVENT", "").strip() == "pull_request_review":
                    state_changed = bot.handle_workflow_run_event(state)
                else:
                    print(
                        "Ignoring workflow_run event with unsupported source event: "
                        f"{os.environ.get('WORKFLOW_RUN_EVENT', '').strip() or '<missing>'}"
                    )

        touched_items = bot.drain_touched_items()

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
            status_labels_changed = bot.sync_status_labels_for_items(state, touched_items)

        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as output_file:
            output_file.write(
                "state_changed=true\n"
                if (state_changed or bool(sync_changes) or bool(restored) or status_labels_changed)
                else "state_changed=false\n"
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
