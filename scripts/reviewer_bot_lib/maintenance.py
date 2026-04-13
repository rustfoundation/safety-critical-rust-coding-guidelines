"""Manual maintenance and operator-dispatch handlers for reviewer-bot."""

from __future__ import annotations

import yaml

from . import maintenance_privileged, maintenance_schedule, reviews
from .event_inputs import build_manual_dispatch_request
from .project_board import (
    format_preview_for_output,
    preview_board_projection_for_item,
    reviewer_board_preflight,
)

ScheduleHandlerResult = maintenance_schedule.ScheduleHandlerResult
_now_iso = maintenance_privileged._now_iso
_finalize_schedule_result = maintenance_schedule._finalize_schedule_result
_record_maintenance_repair_marker = maintenance_schedule._record_maintenance_repair_marker
_run_tracked_pr_repairs = maintenance_schedule._run_tracked_pr_repairs
repair_missing_reviewer_review_state = maintenance_schedule.repair_missing_reviewer_review_state
maybe_record_head_observation_repair = maintenance_schedule.maybe_record_head_observation_repair
check_overdue_reviews = maintenance_schedule.check_overdue_reviews
handle_overdue_review_warning = maintenance_schedule.handle_overdue_review_warning
backfill_transition_notice_if_present = maintenance_schedule.backfill_transition_notice_if_present
handle_transition_notice = maintenance_schedule.handle_transition_notice
sweep_deferred_gaps = maintenance_schedule.sweep_deferred_gaps


def status_projection_repair_needed(bot, state: dict) -> bool:
    current_epoch = state.get("status_projection_epoch")
    return current_epoch != bot.STATUS_PROJECTION_EPOCH


def collect_status_projection_repair_items(bot, state: dict) -> list[int]:
    return maintenance_schedule.collect_status_projection_repair_items(bot, state)


def handle_manual_dispatch(bot, state: dict) -> bool:
    request = build_manual_dispatch_request(bot)
    action = request.action
    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False
    if action == "preview-reviewer-board":
        preflight = reviewer_board_preflight(bot)
        if not preflight.enabled:
            print("Reviewer board preview skipped: reviewer board is disabled.")
            return False
        if not preflight.valid:
            raise RuntimeError(
                "Reviewer board preview preflight failed: " + "; ".join(preflight.errors)
            )

        issue_numbers: list[int] = []
        if request.issue_number:
            issue_numbers = [request.issue_number]
        else:
            active_reviews = state.get("active_reviews")
            if isinstance(active_reviews, dict):
                candidates: set[int] = set()
                for issue_key, review_data in active_reviews.items():
                    if not isinstance(review_data, dict):
                        continue
                    try:
                        issue_number = int(issue_key)
                    except (TypeError, ValueError):
                        continue
                    if issue_number > 0:
                        candidates.add(issue_number)
                issue_numbers = sorted(candidates)

        previews = [preview_board_projection_for_item(bot, state, issue_number) for issue_number in issue_numbers]
        print(
            yaml.safe_dump(
                format_preview_for_output(preflight, previews),
                default_flow_style=False,
                sort_keys=False,
            ).rstrip()
        )
        return False
    bot.assert_lock_held("handle_manual_dispatch")
    if action == "sync-members":
        _, changes = bot.adapters.workflow.sync_members_with_queue(state)
        return bool(changes)
    if action == "repair-review-status-labels":
        for issue_number in reviews.list_open_items_with_status_labels(bot):
            bot.collect_touched_item(issue_number)
        return False
    if action == "check-overdue":
        return maintenance_schedule.handle_scheduled_check_result(bot, state).state_changed
    if action == "execute-pending-privileged-command":
        source_event_key = request.privileged_source_event_key
        if not source_event_key:
            raise RuntimeError("Missing PRIVILEGED_SOURCE_EVENT_KEY for privileged command execution")
        return maintenance_privileged.execute_pending_privileged_command(bot, state, source_event_key)
    return False


def handle_scheduled_check_result(bot, state: dict) -> ScheduleHandlerResult:
    return maintenance_schedule.handle_scheduled_check_result(bot, state)
