"""Core owner for local-state-only review mutation.

Future changes that belong here:
- review-entry defaulting and compatibility upgrades for local mutation APIs
- channel-event acceptance and semantic-key tracking
- reviewer activity updates, completion marking, and cycle-local resets

Future changes that do not belong here:
- live GitHub review reads or preferred-review selection
- replay policy, approval policy, sweeper diagnosis, or privileged planning

Old module no longer preferred for these local-state-only behaviors:
- scripts/reviewer_bot_lib/review_state.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.reviewer_bot_lib.reviews import parse_github_timestamp

from . import state_adapters


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_extra_persisted_fields(review_entry: dict[str, Any]) -> None:
    if "repair_needed" not in review_entry:
        review_entry["repair_needed"] = None
    for mapping in ("deferred_gaps", "observer_discovery_watermarks", "pending_privileged_commands"):
        current = review_entry.get(mapping)
        if not isinstance(current, dict):
            review_entry[mapping] = {}
    reconciled_source_events = review_entry.get("reconciled_source_events")
    if not isinstance(reconciled_source_events, list):
        review_entry["reconciled_source_events"] = []


def _ensure_channel_map(review_entry: dict[str, Any], name: str) -> dict[str, Any]:
    value = review_entry.get(name)
    if not isinstance(value, dict):
        value = {"accepted": None, "seen_keys": []}
        review_entry[name] = value
    if not isinstance(value.get("seen_keys"), list):
        value["seen_keys"] = []
    return value


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    issue_key = str(issue_number)
    if "active_reviews" not in state or not isinstance(state.get("active_reviews"), dict):
        state["active_reviews"] = {}
    review_entry = state["active_reviews"].get(issue_key)
    if review_entry is None:
        if not create:
            return None
        review_entry = {}
        state["active_reviews"][issue_key] = review_entry
    elif isinstance(review_entry, list):
        review_entry = {"skipped": review_entry}
        state["active_reviews"][issue_key] = review_entry
    if not isinstance(review_entry, dict):
        return None

    core_entry = state_adapters.review_entry_from_persisted(review_entry)
    if core_entry is None:
        return None
    state_adapters.apply_local_state_core_to_persisted(review_entry, core_entry)
    _ensure_extra_persisted_fields(review_entry)
    return review_entry


def clear_transition_timers(review_data: dict) -> None:
    review_data["transition_warning_sent"] = None
    review_data["transition_notice_sent_at"] = None


def record_reviewer_activity(review_data: dict, timestamp: str) -> bool:
    current = parse_github_timestamp(review_data.get("last_reviewer_activity"))
    candidate = parse_github_timestamp(timestamp)
    if candidate is None:
        return False
    if current is None or candidate > current:
        review_data["last_reviewer_activity"] = timestamp
        clear_transition_timers(review_data)
        return True
    return False


def record_transition_notice_sent(review_data: dict, timestamp: str) -> None:
    review_data["transition_notice_sent_at"] = timestamp


def _compare_records(left: dict | None, right: dict | None) -> int:
    if right is None:
        return 1
    if left is None:
        return -1
    left_time = parse_github_timestamp(left.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    right_time = parse_github_timestamp(right.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    left_rank = int(left.get("source_precedence", 0))
    right_rank = int(right.get("source_precedence", 0))
    left_key = str(left.get("semantic_key", ""))
    right_key = str(right.get("semantic_key", ""))
    left_tuple = (left_time, left_rank, left_key)
    right_tuple = (right_time, right_rank, right_key)
    if left_tuple > right_tuple:
        return 1
    if left_tuple < right_tuple:
        return -1
    return 0


def semantic_key_seen(review_data: dict, channel_name: str, semantic_key: str) -> bool:
    channel = _ensure_channel_map(review_data, channel_name)
    return semantic_key in channel["seen_keys"]


def accept_channel_event(
    review_data: dict,
    channel_name: str,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str | None = None,
    reviewed_head_sha: str | None = None,
    source_precedence: int = 0,
    payload: dict | None = None,
    dismissal_only: bool = False,
) -> bool:
    channel = _ensure_channel_map(review_data, channel_name)
    if semantic_key in channel["seen_keys"]:
        return False
    channel["seen_keys"].append(semantic_key)
    if dismissal_only:
        channel["accepted"] = channel.get("accepted") or {
            "semantic_key": semantic_key,
            "timestamp": timestamp,
        }
        return True
    candidate = {
        "semantic_key": semantic_key,
        "timestamp": timestamp,
        "actor": actor,
        "reviewed_head_sha": reviewed_head_sha,
        "source_precedence": source_precedence,
        "payload": payload or {},
    }
    current = channel.get("accepted")
    if _compare_records(candidate, current) >= 0:
        channel["accepted"] = candidate
    return True


def _reset_cycle_state(review_data: dict) -> None:
    for channel in (
        "reviewer_comment",
        "reviewer_review",
        "contributor_comment",
        "contributor_revision",
        "review_dismissal",
    ):
        review_data[channel] = {"accepted": None, "seen_keys": []}
    review_data["current_cycle_completion"] = {}
    review_data["current_cycle_write_approval"] = {}
    review_data["overdue_anchor"] = None
    if isinstance(review_data.get("pending_privileged_commands"), dict):
        review_data["pending_privileged_commands"] = {}


def set_current_reviewer(
    state: dict,
    issue_number: int,
    reviewer: str,
    assignment_method: str = "round-robin",
) -> None:
    now = _now_iso()
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return
    review_data["current_reviewer"] = reviewer
    review_data["cycle_started_at"] = now
    review_data["active_cycle_started_at"] = now
    review_data["assigned_at"] = now
    record_reviewer_activity(review_data, now)
    review_data["assignment_method"] = assignment_method
    review_data["review_completed_at"] = None
    review_data["review_completed_by"] = None
    review_data["review_completion_source"] = None
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_label_applied_at"] = None
    review_data["mandatory_approver_pinged_at"] = None
    review_data["mandatory_approver_satisfied_by"] = None
    review_data["mandatory_approver_satisfied_at"] = None
    review_data["active_head_sha"] = None
    _reset_cycle_state(review_data)


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or current_reviewer.lower() != reviewer.lower():
        return False
    record_reviewer_activity(review_data, _now_iso())
    return True


def mark_review_complete(state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    now = _now_iso()
    review_data["review_completed_at"] = now
    review_data["review_completed_by"] = reviewer or None
    review_data["review_completion_source"] = source
    record_reviewer_activity(review_data, now)
    review_data["current_cycle_completion"] = {
        "completed": True,
        "completed_at": now,
        "source": source,
        "reviewer": reviewer,
    }
    return True


def get_current_cycle_boundary(bot, review_data: dict):
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        boundary = bot.parse_iso8601_timestamp(review_data.get(field))
        if boundary is not None:
            return boundary
    return None


def accept_reviewer_review_from_live_review(review_data: dict, review: dict, *, actor: str | None = None) -> bool:
    from . import review_state_live_repair

    return review_state_live_repair.accept_reviewer_review_from_live_review(
        review_data,
        review,
        actor=actor,
    )


def refresh_reviewer_review_from_live_preferred_review(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
    actor: str | None = None,
) -> tuple[bool, dict | None]:
    from . import review_state_live_repair

    return review_state_live_repair.refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
        actor=actor,
    )


def repair_missing_reviewer_review_state(bot, issue_number: int, review_data: dict, *, reviews: list[dict] | None = None) -> bool:
    from . import review_state_live_repair

    return review_state_live_repair.repair_missing_reviewer_review_state(
        bot,
        issue_number,
        review_data,
        reviews=reviews,
    )
