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

from . import live_review_support


def compute_pr_approval_state_from_reviews(
    survivors: dict[str, dict],
    *,
    current_head: str,
    permission_statuses: dict[str, str],
) -> dict[str, object]:
    approvals = [review for review in survivors.values() if str(review.get("state", "")).upper() == "APPROVED"]
    completion = {
        "completed": bool(approvals),
        "current_head_sha": current_head,
        "qualifying_review_ids": [review.get("id") for review in approvals],
    }

    has_write_approval = False
    write_approvers: list[str] = []
    for review in approvals:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        status = permission_statuses.get(author.lower(), "unavailable")
        if status == "unavailable":
            return {"ok": False, "reason": "permission_unavailable"}
        if status == "granted":
            has_write_approval = True
            write_approvers.append(author)

    write_approval = {
        "has_write_approval": has_write_approval,
        "write_approvers": write_approvers,
        "current_head_sha": current_head,
    }
    return {
        "ok": True,
        "completion": completion,
        "write_approval": write_approval,
        "current_head_sha": current_head,
    }


def compute_pr_approval_state_result(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    boundary = live_review_support.get_current_cycle_boundary(
        review_data,
        parse_timestamp=bot.parse_iso8601_timestamp,
    )
    if boundary is None:
        return live_review_support.projection_failure_result("pull_request_unavailable")
    pull_request_result = live_review_support.read_pull_request_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return pull_request_result
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return live_review_support.projection_failure_result("pull_request_head_unavailable", "invalid_payload")
    reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews)
    if not reviews_result.get("ok"):
        return reviews_result
    reviews = reviews_result["reviews"]

    normalized_reviews = live_review_support.normalize_reviews_with_parsed_timestamps(
        reviews,
        parse_timestamp=live_review_support.parse_github_timestamp,
    )
    survivors = live_review_support.filter_current_head_reviews_for_cycle(
        normalized_reviews,
        boundary=boundary,
        current_head=current_head,
    )
    permission_cache = live_review_support.collect_permission_statuses(
        survivors,
        permission_status=lambda author: live_review_support.permission_status(bot, author, "push"),
    )
    result = compute_pr_approval_state_from_reviews(
        survivors,
        current_head=current_head,
        permission_statuses=permission_cache,
    )
    if not result.get("ok"):
        return live_review_support.projection_failure_result(str(result.get("reason")))
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
        submitted_at = live_review_support.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = live_review_support.permission_status(bot, author, "triage") == "granted"
        if permission_cache[cache_key]:
            return author, submitted_at
    return None
