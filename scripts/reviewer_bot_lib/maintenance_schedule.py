"""Scheduled maintenance seam for reviewer-bot."""

from __future__ import annotations

from dataclasses import dataclass

from .lifecycle import handle_transition_notice, maybe_record_head_observation_repair
from .overdue import (
    backfill_transition_notice_if_present,
    check_overdue_reviews,
    handle_overdue_review_warning,
)
from .repair_records import (
    clear_repair_marker,
    load_repair_marker,
    maintenance_repair_marker,
    store_repair_marker,
)
from .review_state import (
    list_open_tracked_review_items,
    repair_missing_reviewer_review_state,
)
from .sweeper import sweep_deferred_gaps


@dataclass(frozen=True)
class ScheduleHandlerResult:
    state_changed: bool
    touched_items: list[int]


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def _clear_maintenance_repair_marker(review_data: dict, phase: str) -> bool:
    marker = load_repair_marker(review_data, phase)
    if not isinstance(marker, dict):
        return False
    if marker.get("kind") != "live_read_failure":
        return False
    return clear_repair_marker(review_data, phase)


def _repair_marker_matches(existing: dict | None, candidate: dict) -> bool:
    if not isinstance(existing, dict):
        return False
    return {key: value for key, value in existing.items() if key != "recorded_at"} == {
        key: value for key, value in candidate.items() if key != "recorded_at"
    }


def _record_maintenance_repair_marker(bot, review_data: dict, *, phase: str, reason: str, failure_kind: str | None) -> bool:
    marker = maintenance_repair_marker(
        reason=reason,
        failure_kind=failure_kind,
        recorded_at=_now_iso(bot),
    )
    existing_marker = load_repair_marker(review_data, phase)
    if _repair_marker_matches(existing_marker, marker):
        return False
    return store_repair_marker(review_data, phase, marker)


def _run_deferred_gap_sweep(bot, state: dict) -> bool:
    return sweep_deferred_gaps(bot, state)


def _run_tracked_pr_repair(bot, issue_number: int, review_data: dict) -> bool:
    changed = False
    try:
        if repair_missing_reviewer_review_state(bot, issue_number, review_data):
            changed = True
            bot.collect_touched_item(issue_number)
        if _clear_maintenance_repair_marker(review_data, "review_repair"):
            changed = True
    except Exception as exc:
        _log(bot, "warning", f"Scheduled repair failed for #{issue_number} during review_repair: {exc}", issue_number=issue_number, phase="review_repair", error=str(exc))
        if _record_maintenance_repair_marker(bot, review_data, phase="review_repair", reason=str(exc), failure_kind=None):
            changed = True
        return changed

    try:
        repair_result = maybe_record_head_observation_repair(bot, issue_number, review_data)
    except Exception as exc:
        _log(bot, "warning", f"Scheduled repair failed for #{issue_number} during head_observation_repair: {exc}", issue_number=issue_number, phase="head_observation_repair", error=str(exc))
        if _record_maintenance_repair_marker(bot, review_data, phase="head_observation_repair", reason=str(exc), failure_kind=None):
            changed = True
        return changed

    if repair_result.changed:
        changed = True
        bot.collect_touched_item(issue_number)
    if repair_result.outcome in {"skipped_unavailable", "skipped_not_found", "invalid_live_payload"}:
        if _record_maintenance_repair_marker(bot, review_data, phase="head_observation_repair", reason=repair_result.reason or repair_result.outcome, failure_kind=repair_result.failure_kind):
            changed = True
    elif _clear_maintenance_repair_marker(review_data, "head_observation_repair"):
        changed = True
    return changed


def _run_tracked_pr_repairs(bot, state: dict) -> bool:
    changed = False
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict) or not review_data.get("current_reviewer"):
            continue
        issue_number = int(issue_key)
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
        if not isinstance(issue_snapshot, dict) or not isinstance(issue_snapshot.get("pull_request"), dict):
            continue
        changed = _run_tracked_pr_repair(bot, issue_number, review_data) or changed
    return changed


def _run_overdue_pass(bot, state: dict) -> bool:
    changed = False
    overdue_reviews = check_overdue_reviews(bot, state)
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        if review["needs_warning"]:
            if handle_overdue_review_warning(bot, state, issue_number, reviewer):
                changed = True
        elif review["needs_transition"]:
            if backfill_transition_notice_if_present(bot, state, issue_number):
                changed = True
            elif handle_transition_notice(bot, state, issue_number, reviewer):
                changed = True
    return changed


def _finalize_schedule_result(bot, state_changed: bool) -> ScheduleHandlerResult:
    return ScheduleHandlerResult(state_changed=state_changed, touched_items=bot.drain_touched_items())


def handle_scheduled_check_result(bot, state: dict) -> ScheduleHandlerResult:
    bot.assert_lock_held("handle_scheduled_check_result")
    changed = _run_deferred_gap_sweep(bot, state)
    changed = _run_tracked_pr_repairs(bot, state) or changed
    changed = _run_overdue_pass(bot, state) or changed
    return _finalize_schedule_result(bot, changed)


def collect_status_projection_repair_items(bot, state: dict) -> list[int]:
    from . import reviews

    numbers = set(reviews.list_open_items_with_status_labels(bot))
    numbers.update(list_open_tracked_review_items(state))
    return sorted(number for number in numbers if isinstance(number, int) and number > 0)
