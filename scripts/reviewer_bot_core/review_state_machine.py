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

from . import state_adapters
from .live_review_support import parse_github_timestamp


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
    state_adapters.ensure_sidecar_subtree(review_entry, state_last_updated=state.get("last_updated"))
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


def upsert_channel_accepted_record(review_data: dict, channel_name: str, record: dict) -> bool:
    channel = _ensure_channel_map(review_data, channel_name)
    changed = False
    if record["semantic_key"] not in channel["seen_keys"]:
        channel["seen_keys"].append(record["semantic_key"])
        changed = True
    if channel.get("accepted") != record:
        channel["accepted"] = record
        changed = True
    return changed


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


def set_current_reviewer(
    state: dict,
    issue_number: int,
    reviewer: str,
    *,
    now: str,
    assignment_method: str = "round-robin",
) -> None:
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


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str, *, now: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or current_reviewer.lower() != reviewer.lower():
        return False
    record_reviewer_activity(review_data, now)
    return True


def mark_review_complete(state: dict, issue_number: int, reviewer: str | None, source: str, *, completed_at: str) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    review_data["review_completed_at"] = completed_at
    review_data["review_completed_by"] = reviewer or None
    review_data["review_completion_source"] = source
    record_reviewer_activity(review_data, completed_at)
    review_data["current_cycle_completion"] = {
        "completed": True,
        "completed_at": completed_at,
        "source": source,
        "reviewer": reviewer,
    }
    return True
