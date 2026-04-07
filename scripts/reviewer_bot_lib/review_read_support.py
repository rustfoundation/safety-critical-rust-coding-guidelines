"""Review-read support owner for live PR normalization and projection failures."""

from __future__ import annotations

from datetime import datetime


def _projection_failure(reason: str, failure_kind: str | None = None) -> dict[str, object]:
    return {"ok": False, "reason": reason, "failure_kind": failure_kind}


def _fallback_pull_request_payload(bot, issue_number: int) -> dict[str, object]:
    payload = bot.github_api("GET", f"pulls/{issue_number}")
    if isinstance(payload, dict):
        return {"ok": True, "pull_request": payload}
    return _projection_failure("pull_request_unavailable")


def _pull_request_read_result(bot, issue_number: int, pull_request: dict | None = None) -> dict[str, object]:
    if pull_request is not None:
        if isinstance(pull_request, dict):
            return {"ok": True, "pull_request": pull_request}
        return _projection_failure("pull_request_unavailable", "invalid_payload")
    try:
        response = bot.github_api_request("GET", f"pulls/{issue_number}", retry_policy="idempotent_read")
    except SystemExit:
        return _fallback_pull_request_payload(bot, issue_number)
    if not response.ok:
        if response.failure_kind == "not_found":
            return _projection_failure("pull_request_not_found", response.failure_kind)
        return _projection_failure("pull_request_unavailable", response.failure_kind)
    if not isinstance(response.payload, dict):
        return _projection_failure("pull_request_unavailable", "invalid_payload")
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
            return _projection_failure("reviews_unavailable")
        page_reviews = [review for review in payload if isinstance(review, dict)]
        collected_reviews.extend(page_reviews)
        if len(payload) < 100:
            return {"ok": True, "reviews": collected_reviews}
        page += 1


def get_pull_request_reviews_result(bot, issue_number: int, reviews: list[dict] | None = None) -> dict[str, object]:
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
            return _projection_failure("reviews_unavailable", response.failure_kind)
        payload = response.payload
        if not isinstance(payload, list):
            return _projection_failure("reviews_unavailable", "invalid_payload")
        page_reviews = [review for review in payload if isinstance(review, dict)]
        collected_reviews.extend(page_reviews)
        if len(payload) < 100:
            return {"ok": True, "reviews": collected_reviews}
        page += 1


def _permission_status(bot, username: str, permission: str) -> str:
    status = bot.github.get_user_permission_status(username, permission)
    if status not in {"granted", "denied", "unavailable"}:
        return "unavailable"
    return status


def parse_github_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
