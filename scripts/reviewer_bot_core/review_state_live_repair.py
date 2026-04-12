"""Live-read-assisted review repair owner.

Future changes that belong here:
- applying already-selected live reviewer reviews into persisted reviewer_review state
- activity refresh and repair decisions once live review inputs are available

Future changes that do not belong here:
- persisted entry defaulting or local-only state mutation rules
- raw GitHub runtime access or direct review fetching

Old module no longer preferred for these live-read-assisted repair changes:
- scripts/reviewer_bot_core/review_state_machine.py
"""

from __future__ import annotations

from . import live_review_support, review_state_machine, reviewer_review_helpers


def accept_reviewer_review_from_live_review(review_data: dict, review: dict, *, actor: str | None = None) -> bool:
    record = reviewer_review_helpers.build_reviewer_review_record_from_live_review(review, actor=actor)
    if record is None:
        return False
    return review_state_machine.accept_channel_event(
        review_data,
        "reviewer_review",
        semantic_key=record["semantic_key"],
        timestamp=record["timestamp"],
        actor=record["actor"],
        reviewed_head_sha=record["reviewed_head_sha"],
        source_precedence=record["source_precedence"],
        payload=record["payload"],
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
    if pull_request is None:
        pull_request_result = live_review_support.read_pull_request_result(bot, issue_number)
        if not pull_request_result.get("ok"):
            return False, None
        pull_request = pull_request_result["pull_request"]
    preferred_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if preferred_review is None:
        return False, None
    record = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
        preferred_review,
        actor=actor or review_data.get("current_reviewer"),
    )
    if record is None:
        return False, None
    changed = review_state_machine.upsert_channel_accepted_record(review_data, "reviewer_review", record)
    submitted_at = preferred_review.get("submitted_at")
    if isinstance(submitted_at, str):
        previous_activity = review_data.get("last_reviewer_activity")
        previous_warning = review_data.get("transition_warning_sent")
        previous_notice = review_data.get("transition_notice_sent_at")
        review_state_machine.record_reviewer_activity(review_data, submitted_at)
        activity_changed = (
            previous_activity != review_data.get("last_reviewer_activity")
            or previous_warning != review_data.get("transition_warning_sent")
            or previous_notice != review_data.get("transition_notice_sent_at")
        )
        changed = changed or activity_changed
    return changed, preferred_review


def repair_missing_reviewer_review_state(bot, issue_number: int, review_data: dict, *, reviews: list[dict] | None = None) -> bool:
    changed, _ = refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        reviews=reviews,
        actor=review_data.get("current_reviewer"),
    )
    return changed
