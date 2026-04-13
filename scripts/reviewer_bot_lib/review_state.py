"""Public mutable review-state operations shared across reviewer-bot modules."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.reviewer_bot_core import (
    live_review_support,
    review_state_live_repair,
    review_state_machine,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    return review_state_machine.ensure_review_entry(state, issue_number, create=create)


def clear_transition_timers(review_data: dict) -> None:
    review_state_machine.clear_transition_timers(review_data)


def record_reviewer_activity(review_data: dict, timestamp: str) -> bool:
    return review_state_machine.record_reviewer_activity(review_data, timestamp)


def record_transition_notice_sent(review_data: dict, timestamp: str) -> None:
    review_state_machine.record_transition_notice_sent(review_data, timestamp)


def set_current_reviewer(
    state: dict,
    issue_number: int,
    reviewer: str,
    assignment_method: str = "round-robin",
) -> None:
    review_state_machine.set_current_reviewer(
        state,
        issue_number,
        reviewer,
        now=_now_iso(),
        assignment_method=assignment_method,
    )


def semantic_key_seen(review_data: dict, channel_name: str, semantic_key: str) -> bool:
    return review_state_machine.semantic_key_seen(review_data, channel_name, semantic_key)


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
    return review_state_machine.accept_channel_event(
        review_data,
        channel_name,
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
        reviewed_head_sha=reviewed_head_sha,
        source_precedence=source_precedence,
        payload=payload,
        dismissal_only=dismissal_only,
    )


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    return review_state_machine.update_reviewer_activity(state, issue_number, reviewer, now=_now_iso())


def mark_review_complete(state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
    return review_state_machine.mark_review_complete(state, issue_number, reviewer, source, completed_at=_now_iso())


def get_current_cycle_boundary(bot, review_data: dict) -> datetime | None:
    return live_review_support.get_current_cycle_boundary(review_data, parse_timestamp=bot.parse_iso8601_timestamp)


def accept_reviewer_review_from_live_review(review_data: dict, review: dict, *, actor: str | None = None) -> bool:
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
    return review_state_live_repair.refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
        actor=actor,
    )


def repair_missing_reviewer_review_state(bot, issue_number: int, review_data: dict, *, reviews: list[dict] | None = None) -> bool:
    return review_state_live_repair.repair_missing_reviewer_review_state(
        bot,
        issue_number,
        review_data,
        reviews=reviews,
    )


def list_open_tracked_review_items(state: dict) -> list[int]:
    numbers: set[int] = set()
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return []
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        current_reviewer = review_data.get("current_reviewer")
        if not isinstance(current_reviewer, str) or not current_reviewer.strip():
            continue
        try:
            issue_number = int(issue_key)
        except (TypeError, ValueError):
            continue
        if issue_number > 0:
            numbers.add(issue_number)
    return sorted(numbers)
