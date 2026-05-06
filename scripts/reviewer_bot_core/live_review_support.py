"""Core-local live-review support helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ReviewFreshnessClassification:
    review_id: int | str
    author: str | None
    state: str | None
    submitted_at: str | None
    commit_id: str | None
    classified_scope: str
    is_assigned_reviewer: bool
    is_current_head: bool
    is_after_cycle_boundary: bool
    is_dismissed_or_superseded: bool
    diagnostic_reason: str | None
    payload: dict[str, object]

    def to_output(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "author": self.author,
            "state": self.state,
            "submitted_at": self.submitted_at,
            "commit_id": self.commit_id,
            "classified_scope": self.classified_scope,
            "is_assigned_reviewer": self.is_assigned_reviewer,
            "is_current_head": self.is_current_head,
            "is_after_cycle_boundary": self.is_after_cycle_boundary,
            "is_dismissed_or_superseded": self.is_dismissed_or_superseded,
            "diagnostic_reason": self.diagnostic_reason,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class CurrentReviewContext:
    issue_number: int
    current_head_sha: str | None
    cycle_boundary: str | None
    live_reviews_available: bool
    live_reviews_failure_kind: str | None
    classifications: tuple[ReviewFreshnessClassification, ...]

    def to_output(self) -> dict[str, object]:
        classifications = sorted(
            self.classifications,
            key=lambda item: (item.submitted_at or "", str(item.review_id), item.author or ""),
        )
        return {
            "issue_number": self.issue_number,
            "current_head_sha": self.current_head_sha,
            "cycle_boundary": self.cycle_boundary,
            "live_reviews_available": self.live_reviews_available,
            "live_reviews_failure_kind": self.live_reviews_failure_kind,
            "classifications": [item.to_output() for item in classifications],
        }


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
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


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


def _timestamp_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return parse_github_timestamp(value)


def classify_review_freshness(
    review,
    *,
    current_head_sha: str | None,
    cycle_boundary: object | None,
    assigned_reviewer: str | None,
) -> ReviewFreshnessClassification:
    review_id = getattr(review, "review_id", None)
    author = getattr(review, "author", None)
    state = getattr(review, "state", None)
    submitted_at = getattr(review, "submitted_at", None)
    commit_id = getattr(review, "commit_id", None)
    payload = getattr(review, "payload", {})
    if not isinstance(payload, dict):
        payload = {}
    malformed = not review_id or not isinstance(state, str) or not state.strip()
    is_dismissed = isinstance(state, str) and state.upper() == "DISMISSED"
    submitted_dt = _timestamp_value(submitted_at)
    boundary_dt = _timestamp_value(cycle_boundary)
    is_after_boundary = boundary_dt is None or (submitted_dt is not None and submitted_dt >= boundary_dt)
    is_current_head = isinstance(commit_id, str) and isinstance(current_head_sha, str) and commit_id.strip() == current_head_sha.strip()
    is_assigned = isinstance(author, str) and isinstance(assigned_reviewer, str) and author.lower() == assigned_reviewer.lower()
    if malformed:
        scope = "malformed"
        reason = "malformed_review_snapshot"
    elif is_dismissed:
        scope = "dismissed_or_superseded"
        reason = "review_dismissed_or_superseded"
    elif not is_after_boundary:
        scope = "before_cycle"
        reason = "review_before_cycle_boundary"
    elif not is_current_head:
        scope = "stale_head"
        reason = "review_not_on_current_head"
    elif is_assigned:
        scope = "current_head_assigned_reviewer"
        reason = None
    elif isinstance(author, str) and author.strip():
        scope = "current_head_alternate_reviewer"
        reason = "alternate_reviewer_diagnostic_only"
    else:
        scope = "unknown"
        reason = "unknown_review_author"
    return ReviewFreshnessClassification(
        review_id=review_id if isinstance(review_id, (int, str)) else "",
        author=author if isinstance(author, str) and author.strip() else None,
        state=state.upper() if isinstance(state, str) and state.strip() else None,
        submitted_at=submitted_at if isinstance(submitted_at, str) and submitted_at.strip() else None,
        commit_id=commit_id if isinstance(commit_id, str) and commit_id.strip() else None,
        classified_scope=scope,
        is_assigned_reviewer=is_assigned,
        is_current_head=is_current_head,
        is_after_cycle_boundary=is_after_boundary,
        is_dismissed_or_superseded=is_dismissed,
        diagnostic_reason=reason,
        payload=payload,
    )


def filter_current_head_reviews_for_cycle(
    reviews: list[dict],
    *,
    boundary: datetime,
    current_head: str,
) -> dict[str, dict]:
    survivors: dict[str, dict] = {}
    from . import reviewer_review_helpers

    for review in reviews:
        if not isinstance(review, dict):
            continue
        snapshot = reviewer_review_helpers.build_review_snapshot_record(review)
        if snapshot is None:
            continue
        classification = classify_review_freshness(
            snapshot,
            current_head_sha=current_head,
            cycle_boundary=boundary,
            assigned_reviewer=None,
        )
        if classification.classified_scope not in {
            "current_head_assigned_reviewer",
            "current_head_alternate_reviewer",
        }:
            continue
        submitted_at = review.get("submitted_at")
        if not isinstance(submitted_at, datetime):
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


def build_current_review_context(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> CurrentReviewContext:
    from . import reviewer_review_helpers

    pull_request_result = read_pull_request_result(bot, issue_number, pull_request)
    current_head_sha = None
    if pull_request_result.get("ok"):
        head = pull_request_result.get("pull_request", {}).get("head")
        current_head_sha = head.get("sha") if isinstance(head, dict) else None
    boundary = get_current_cycle_boundary(review_data, parse_timestamp=parse_github_timestamp)
    cycle_boundary = boundary.isoformat() if isinstance(boundary, datetime) else None
    reviews_result = read_pull_request_reviews_result(bot, issue_number, reviews)
    if not reviews_result.get("ok"):
        return CurrentReviewContext(
            issue_number=issue_number,
            current_head_sha=current_head_sha,
            cycle_boundary=cycle_boundary,
            live_reviews_available=False,
            live_reviews_failure_kind=str(reviews_result.get("failure_kind") or reviews_result.get("reason") or "unavailable"),
            classifications=(),
        )
    assigned_reviewer = review_data.get("current_reviewer") if isinstance(review_data.get("current_reviewer"), str) else None
    classifications = []
    for review in reviews_result.get("reviews", []):
        snapshot = reviewer_review_helpers.build_review_snapshot_record(review)
        if snapshot is None:
            continue
        classifications.append(
            classify_review_freshness(
                snapshot,
                current_head_sha=current_head_sha,
                cycle_boundary=cycle_boundary,
                assigned_reviewer=assigned_reviewer,
            )
        )
    return CurrentReviewContext(
        issue_number=issue_number,
        current_head_sha=current_head_sha if isinstance(current_head_sha, str) and current_head_sha.strip() else None,
        cycle_boundary=cycle_boundary,
        live_reviews_available=True,
        live_reviews_failure_kind=None,
        classifications=tuple(classifications),
    )


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
