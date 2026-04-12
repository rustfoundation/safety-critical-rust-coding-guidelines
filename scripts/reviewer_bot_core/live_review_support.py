"""Core-local live-review support helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def get_current_cycle_boundary(review_data: dict, *, parse_timestamp) -> datetime | None:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        boundary = parse_timestamp(review_data.get(field))
        if boundary is not None:
            return boundary
    return None


def parse_github_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def projection_failure_result(reason: str, failure_kind: str | None = None) -> dict[str, object]:
    return {"ok": False, "reason": reason, "failure_kind": failure_kind}


def _fallback_pull_request_payload(bot, issue_number: int) -> dict[str, object]:
    payload = bot.github_api("GET", f"pulls/{issue_number}")
    if isinstance(payload, dict):
        return {"ok": True, "pull_request": payload}
    return projection_failure_result("pull_request_unavailable")


def read_pull_request_result(bot, issue_number: int, pull_request: dict | None = None) -> dict[str, object]:
    if pull_request is not None:
        if isinstance(pull_request, dict):
            return {"ok": True, "pull_request": pull_request}
        return projection_failure_result("pull_request_unavailable", "invalid_payload")
    try:
        response = bot.github_api_request("GET", f"pulls/{issue_number}", retry_policy="idempotent_read")
    except SystemExit:
        return _fallback_pull_request_payload(bot, issue_number)
    if not response.ok:
        if response.failure_kind == "not_found":
            return projection_failure_result("pull_request_not_found", response.failure_kind)
        return projection_failure_result("pull_request_unavailable", response.failure_kind)
    if not isinstance(response.payload, dict):
        return projection_failure_result("pull_request_unavailable", "invalid_payload")
    return {"ok": True, "pull_request": response.payload}


def _fallback_pull_request_reviews_result(bot, issue_number: int) -> dict[str, object]:
    fallback_reviews = bot.get_pull_request_reviews(issue_number)
    if isinstance(fallback_reviews, list):
        return {"ok": True, "reviews": fallback_reviews}

    collected_reviews: list[dict] = []
    page = 1
    while True:
        payload = bot.github_api("GET", f"pulls/{issue_number}/reviews?per_page=100&page={page}")
        if not isinstance(payload, list):
            return projection_failure_result("reviews_unavailable")
        page_reviews = [review for review in payload if isinstance(review, dict)]
        collected_reviews.extend(page_reviews)
        if len(payload) < 100:
            return {"ok": True, "reviews": collected_reviews}
        page += 1


def read_pull_request_reviews_result(bot, issue_number: int, reviews: list[dict] | None = None) -> dict[str, object]:
    if reviews is not None:
        return {"ok": True, "reviews": reviews}
    collected_reviews: list[dict] = []
    page = 1
    while True:
        try:
            response = bot.github_api_request(
                "GET",
                f"pulls/{issue_number}/reviews?per_page=100&page={page}",
                retry_policy="idempotent_read",
            )
        except SystemExit:
            return _fallback_pull_request_reviews_result(bot, issue_number)
        if not response.ok:
            return projection_failure_result("reviews_unavailable", response.failure_kind)
        payload = response.payload
        if not isinstance(payload, list):
            return projection_failure_result("reviews_unavailable", "invalid_payload")
        page_reviews = [review for review in payload if isinstance(review, dict)]
        collected_reviews.extend(page_reviews)
        if len(payload) < 100:
            return {"ok": True, "reviews": collected_reviews}
        page += 1


def permission_status(bot, username: str, permission: str) -> str:
    status = bot.github.get_user_permission_status(username, permission)
    if status not in {"granted", "denied", "unavailable"}:
        return "unavailable"
    return status


def normalize_reviews_with_parsed_timestamps(reviews: list[dict], *, parse_timestamp) -> list[dict]:
    normalized_reviews = []
    for review in reviews:
        if not isinstance(review, dict):
            normalized_reviews.append(review)
            continue
        normalized = dict(review)
        normalized["submitted_at"] = parse_timestamp(review.get("submitted_at"))
        normalized_reviews.append(normalized)
    return normalized_reviews


def filter_current_head_reviews_for_cycle(
    reviews: list[dict],
    *,
    boundary: datetime,
    current_head: str,
) -> dict[str, dict]:
    survivors: dict[str, dict] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        state = str(review.get("state", "")).upper()
        if state == "DISMISSED":
            continue
        submitted_at = review.get("submitted_at")
        if not isinstance(submitted_at, datetime) or submitted_at < boundary:
            continue
        commit_id = review.get("commit_id")
        if not isinstance(commit_id, str) or not commit_id.strip() or commit_id.strip() != current_head:
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        review_id = str(review.get("id", ""))
        key = author.lower()
        candidate_key = (submitted_at, review_id)
        current = survivors.get(key)
        if current is None:
            survivors[key] = review
            continue
        current_key = (
            current.get("submitted_at") or datetime.min.replace(tzinfo=timezone.utc),
            str(current.get("id", "")),
        )
        if candidate_key >= current_key:
            survivors[key] = review
    return survivors


def collect_permission_statuses(survivors: dict[str, dict], *, permission_status) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for review in survivors.values():
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        cache_key = author.lower()
        if cache_key not in statuses:
            statuses[cache_key] = permission_status(author)
    return statuses
