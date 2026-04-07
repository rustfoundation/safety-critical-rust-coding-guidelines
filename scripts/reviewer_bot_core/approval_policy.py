"""Approval and completion derivation owner.

Future changes that belong here:
- approval/completion derivation from pull-request snapshots, review snapshots, and
  permission observations
- triage-approval derivation from already-fetched review inputs

Future changes that do not belong here:
- reviewer-response derivation
- state mutation, label writes, escalation, or other side effects
- pure projection helper implementations that remain in `reviews_projection.py`

Old module no longer preferred for these derivation changes:
- `scripts/reviewer_bot_lib/reviews.py`
"""

from __future__ import annotations


def compute_pr_approval_state_result(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    from scripts.reviewer_bot_core import review_state_machine
    from scripts.reviewer_bot_lib import reviews as legacy_reviews
    from scripts.reviewer_bot_lib.reviews_projection import (
        collect_permission_statuses,
        compute_pr_approval_state_from_reviews,
        filter_current_head_reviews_for_cycle,
        normalize_reviews_with_parsed_timestamps,
    )

    boundary = review_state_machine.get_current_cycle_boundary(bot, review_data)
    if boundary is None:
        return legacy_reviews._projection_failure("pull_request_unavailable")
    pull_request_result = legacy_reviews._pull_request_read_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return pull_request_result
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return legacy_reviews._projection_failure("pull_request_head_unavailable", "invalid_payload")
    reviews_result = legacy_reviews.get_pull_request_reviews_result(bot, issue_number, reviews)
    if not reviews_result.get("ok"):
        return reviews_result
    reviews = reviews_result["reviews"]

    normalized_reviews = normalize_reviews_with_parsed_timestamps(
        reviews,
        parse_timestamp=legacy_reviews.parse_github_timestamp,
    )
    survivors = filter_current_head_reviews_for_cycle(
        normalized_reviews,
        boundary=boundary,
        current_head=current_head,
    )
    permission_cache = collect_permission_statuses(
        survivors,
        permission_status=lambda author: legacy_reviews._permission_status(bot, author, "push"),
    )
    result = compute_pr_approval_state_from_reviews(
        survivors,
        current_head=current_head,
        permission_statuses=permission_cache,
    )
    if not result.get("ok"):
        return legacy_reviews._projection_failure(str(result.get("reason")))
    return result


def find_triage_approval_after(bot, reviews: list[dict], since) -> tuple[str, object] | None:
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[object, str, str]] = []
    for review in reviews:
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at
    return None
