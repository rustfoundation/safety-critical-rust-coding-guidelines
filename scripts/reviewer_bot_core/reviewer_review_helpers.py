from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import live_review_support


@dataclass(frozen=True)
class ReviewSnapshotRecord:
    review_id: int | str
    state: str
    author: str | None
    submitted_at: str | None
    commit_id: str | None
    source_precedence: int
    payload: dict[str, object]

    def to_output(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "state": self.state,
            "author": self.author,
            "submitted_at": self.submitted_at,
            "commit_id": self.commit_id,
            "source_precedence": self.source_precedence,
            "payload": dict(self.payload),
        }


def compare_records(
    left: dict | None,
    right: dict | None,
    *,
    parse_timestamp,
) -> int:
    if right is None:
        return 1
    if left is None:
        return -1
    left_time = parse_timestamp(left.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    right_time = parse_timestamp(right.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
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


def _review_sort_key(bot, review: dict) -> tuple[datetime, str]:
    return (
        live_review_support.parse_github_timestamp(review.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc),
        str(review.get("id", "")),
    )


def _review_matches_head(review: dict, current_head: str | None) -> bool:
    commit_id = review.get("commit_id") if isinstance(review, dict) else None
    return isinstance(commit_id, str) and isinstance(current_head, str) and commit_id.strip() == current_head.strip()


def get_valid_current_reviewer_reviews_for_cycle(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    current_cycle_boundary,
    reviews: list[dict] | None = None,
) -> list[dict]:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return []
    if current_cycle_boundary is None:
        return []
    if reviews is None:
        reviews = bot.github.get_pull_request_reviews(issue_number)
    if reviews is None:
        return []
    valid_reviews: list[dict] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != current_reviewer.lower():
            continue
        state = str(review.get("state", "")).upper()
        if state not in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}:
            continue
        submitted_at = live_review_support.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None or submitted_at < current_cycle_boundary:
            continue
        commit_id = review.get("commit_id")
        if not isinstance(commit_id, str) or not commit_id.strip():
            continue
        valid_reviews.append(review)
    return valid_reviews


def get_preferred_current_reviewer_review_for_cycle(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict | None:
    from . import live_review_support

    valid_reviews = get_valid_current_reviewer_reviews_for_cycle(
        bot,
        issue_number,
        review_data,
        current_cycle_boundary=live_review_support.get_current_cycle_boundary(
            review_data,
            parse_timestamp=bot.parse_iso8601_timestamp,
        ),
        reviews=reviews,
    )
    if not valid_reviews:
        return None
    if len(valid_reviews) == 1:
        return valid_reviews[0]
    head = pull_request.get("head") if isinstance(pull_request, dict) else None
    current_head = head.get("sha") if isinstance(head, dict) else None
    current_head_reviews = [review for review in valid_reviews if _review_matches_head(review, current_head)]
    candidates = current_head_reviews or valid_reviews
    return max(candidates, key=lambda review: _review_sort_key(bot, review), default=None)


def build_reviewer_review_record_from_live_review(review: dict, *, actor: str | None = None) -> dict | None:
    snapshot = build_review_snapshot_record(review, actor=actor)
    if snapshot is None:
        return None
    if snapshot.submitted_at is None or snapshot.commit_id is None or snapshot.author is None:
        return None
    return {
        "semantic_key": f"pull_request_review:{snapshot.review_id}",
        "timestamp": snapshot.submitted_at,
        "actor": snapshot.author,
        "reviewed_head_sha": snapshot.commit_id,
        "source_precedence": 1,
        "payload": snapshot.to_output(),
    }


def build_review_snapshot_record(review: dict, *, actor: str | None = None) -> ReviewSnapshotRecord | None:
    if not isinstance(review, dict):
        return None
    review_id = review.get("id")
    state = review.get("state")
    submitted_at = review.get("submitted_at")
    commit_id = review.get("commit_id")
    author = actor if isinstance(actor, str) and actor.strip() else review.get("user", {}).get("login")
    if not isinstance(review_id, (int, str)) or not str(review_id).strip():
        return None
    if not isinstance(state, str) or not state.strip():
        return None
    payload = {key: value for key, value in review.items() if key not in {"body"}}
    return ReviewSnapshotRecord(
        review_id=review_id,
        state=state.upper(),
        author=author if isinstance(author, str) and author.strip() else None,
        submitted_at=submitted_at if isinstance(submitted_at, str) and submitted_at.strip() else None,
        commit_id=commit_id if isinstance(commit_id, str) and commit_id.strip() else None,
        source_precedence=1,
        payload=payload,
    )
