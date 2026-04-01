"""Pure projection helpers for reviewer-bot review state."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import (
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
)


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


def normalize_reviews_with_parsed_timestamps(
    reviews: list[dict],
    *,
    parse_timestamp,
) -> list[dict]:
    normalized_reviews = []
    for review in reviews:
        if not isinstance(review, dict):
            normalized_reviews.append(review)
            continue
        normalized = dict(review)
        normalized["submitted_at"] = parse_timestamp(review.get("submitted_at"))
        normalized_reviews.append(normalized)
    return normalized_reviews


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


def desired_labels_from_response_state(
    state_name: str,
    reason: str | None,
) -> tuple[set[str] | None, dict[str, str | None]]:
    if state_name == "projection_failed":
        return None, {"state": state_name, "reason": reason}
    if state_name == "awaiting_reviewer_response":
        return {STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}, {"state": state_name, "reason": reason}
    if state_name == "awaiting_contributor_response":
        return {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}, {"state": state_name, "reason": reason}
    if state_name == "awaiting_write_approval":
        return {STATUS_AWAITING_WRITE_APPROVAL_LABEL}, {"state": state_name, "reason": reason}
    return set(), {"state": state_name, "reason": reason}
