"""Reviewer-response derivation owner.

Future changes that belong here:
- reviewer-response derivation from stored review state plus already-fetched live PR inputs
- contributor handoff and stale-review response decisions

Future changes that do not belong here:
- label writes, issue writes, or projection application
- mandatory approver escalation

Old module no longer preferred for these reviewer-response decision changes:
- scripts/reviewer_bot_lib/reviews.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import live_review_support, reviewer_review_helpers

_UNSET = object()


def _record_timestamp(record: dict | None, *, parse_timestamp) -> datetime | None:
    if not isinstance(record, dict):
        return None
    return parse_timestamp(record.get("timestamp"))


def _compare_cross_channel_conversation(contributor: dict | None, reviewer: dict | None, *, parse_timestamp) -> int:
    contributor_time = _record_timestamp(contributor, parse_timestamp=parse_timestamp) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    reviewer_time = _record_timestamp(reviewer, parse_timestamp=parse_timestamp) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    contributor_key = str((contributor or {}).get("semantic_key", ""))
    reviewer_key = str((reviewer or {}).get("semantic_key", ""))
    if (contributor_time, contributor_key) == (reviewer_time, reviewer_key):
        return 0
    if contributor_time > reviewer_time:
        return 1
    if contributor_time < reviewer_time:
        return -1
    if contributor_key >= reviewer_key:
        return 1
    return -1


def _initial_reviewer_anchor(review_data: dict) -> str | None:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        value = review_data.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _contributor_revision_handoff_record(review_data: dict, current_head: str | None, reviewer_review: dict | None) -> dict | None:
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    if not isinstance(contributor_revision, dict):
        return None
    revision_head = contributor_revision.get("reviewed_head_sha")
    if not isinstance(revision_head, str) or not isinstance(current_head, str):
        return None
    if revision_head != current_head:
        return None
    reviewer_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if isinstance(reviewer_head, str) and reviewer_head == current_head:
        return None
    return contributor_revision


def derive_reviewer_response_state(
    review_data: dict,
    *,
    issue_is_pull_request: bool,
    current_head: str | None = None,
    reviewer_comment: dict | None | object = _UNSET,
    reviewer_review: dict | None | object = _UNSET,
    contributor_comment: dict | None | object = _UNSET,
    had_reviewer_review: bool = False,
    approval_result: dict[str, object] | None = None,
) -> dict[str, object]:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return {"state": "untracked", "reason": "no_current_reviewer"}

    if reviewer_comment is _UNSET:
        reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    if reviewer_review is _UNSET:
        reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    if contributor_comment is _UNSET:
        contributor_comment = review_data.get("contributor_comment", {}).get("accepted")

    if not issue_is_pull_request:
        if not reviewer_comment and not reviewer_review:
            return {
                "state": "awaiting_reviewer_response",
                "reason": "no_reviewer_activity",
                "anchor_timestamp": _initial_reviewer_anchor(review_data),
                "reviewer_comment": reviewer_comment,
                "reviewer_review": reviewer_review,
                "contributor_comment": contributor_comment,
                "contributor_handoff": None,
            }
        latest_reviewer_response = reviewer_comment
        if reviewer_review_helpers.compare_records(
            reviewer_review,
            latest_reviewer_response,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            latest_reviewer_response = reviewer_review
        completion = review_data.get("current_cycle_completion")
        if not isinstance(completion, dict) or not completion.get("completed"):
            if review_data.get("review_completed_at"):
                return {"state": "done", "reason": None}
            return {
                "state": "awaiting_contributor_response",
                "reason": "completion_missing",
                "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            }
        return {"state": "done", "reason": None}

    if not isinstance(current_head, str) or not current_head.strip():
        return {"state": "projection_failed", "reason": "pull_request_head_unavailable"}

    if not reviewer_comment and not reviewer_review:
        if not had_reviewer_review:
            return {
                "state": "awaiting_reviewer_response",
                "reason": "no_reviewer_activity",
                "anchor_timestamp": _initial_reviewer_anchor(review_data),
                "reviewer_comment": reviewer_comment,
                "reviewer_review": reviewer_review,
                "contributor_comment": contributor_comment,
                "contributor_handoff": None,
            }

    latest_reviewer_response = reviewer_comment
    if reviewer_review_helpers.compare_records(
        reviewer_review,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        latest_reviewer_response = reviewer_review

    contributor_handoff = contributor_comment
    contributor_revision = _contributor_revision_handoff_record(
        review_data,
        current_head,
        reviewer_review if isinstance(reviewer_review, dict) else None,
    )
    if reviewer_review_helpers.compare_records(
        contributor_revision,
        contributor_handoff,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        contributor_handoff = contributor_revision

    if _compare_cross_channel_conversation(
        contributor_handoff,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        reason = "contributor_comment_newer"
        if isinstance(contributor_handoff, dict) and str(contributor_handoff.get("semantic_key", "")).startswith(
            "pull_request_"
        ):
            reason = "contributor_revision_newer"
        return {
            "state": "awaiting_reviewer_response",
            "reason": reason,
            "anchor_timestamp": contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }

    latest_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if not isinstance(latest_review_head, str) or latest_review_head != current_head:
        return {
            "state": "awaiting_reviewer_response",
            "reason": "review_head_stale",
            "anchor_timestamp": contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else _initial_reviewer_anchor(review_data),
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }

    if not isinstance(approval_result, dict) or not approval_result.get("ok"):
        return {"state": "projection_failed", "reason": "live_review_state_unknown"}

    completion = approval_result["completion"]
    write_approval = approval_result["write_approval"]
    if not completion.get("completed"):
        return {
            "state": "awaiting_contributor_response",
            "reason": "completion_missing",
            "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }
    if not write_approval.get("has_write_approval"):
        return {
            "state": "awaiting_write_approval",
            "reason": "write_approval_missing",
            "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }
    return {
        "state": "done",
        "reason": "write_approval_present",
        "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
        "current_head_sha": current_head,
        "reviewer_comment": reviewer_comment,
        "reviewer_review": reviewer_review,
        "contributor_comment": contributor_comment,
        "contributor_handoff": contributor_handoff,
    }


def compute_reviewer_response_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    issue_snapshot: dict | None = None,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    if issue_snapshot is None:
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return {"state": "projection_failed", "reason": "issue_snapshot_unavailable"}
    is_pr = isinstance(issue_snapshot.get("pull_request"), dict)

    reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    contributor_comment = review_data.get("contributor_comment", {}).get("accepted")
    had_reviewer_review = isinstance(reviewer_review, dict)

    if not is_pr:
        return derive_reviewer_response_state(
            review_data,
            issue_is_pull_request=False,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            contributor_comment=contributor_comment,
            had_reviewer_review=had_reviewer_review,
        )

    pull_request_result = live_review_support.read_pull_request_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return {"state": "projection_failed", "reason": str(pull_request_result.get("reason"))}
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return {"state": "projection_failed", "reason": "pull_request_head_unavailable"}

    if not reviewer_comment and not reviewer_review:
        reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews)
        if not reviews_result.get("ok"):
            return {"state": "projection_failed", "reason": str(reviews_result.get("reason"))}
        reviews = reviews_result["reviews"]
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )
        if preferred_live_review is not None:
            reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
                preferred_live_review,
                actor=review_data.get("current_reviewer"),
            )

    stored_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    refresh_live_review = reviews is not None or reviewer_review is None
    if not refresh_live_review:
        refresh_live_review = not isinstance(stored_review_head, str) or stored_review_head != current_head

    preferred_live_review = None
    if refresh_live_review:
        reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews)
        if not reviews_result.get("ok"):
            return {"state": "projection_failed", "reason": str(reviews_result.get("reason"))}
        reviews = reviews_result["reviews"]
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )
    if preferred_live_review is not None:
        reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
            preferred_live_review,
            actor=review_data.get("current_reviewer"),
        )
    elif refresh_live_review:
        reviewer_review = None

    approval_result = None
    reviewed_head_sha = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if isinstance(reviewed_head_sha, str) and reviewed_head_sha == current_head:
        from scripts.reviewer_bot_core import approval_policy

        approval_result = approval_policy.compute_pr_approval_state_result(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )

    return derive_reviewer_response_state(
        review_data,
        issue_is_pull_request=True,
        current_head=current_head,
        reviewer_comment=reviewer_comment,
        reviewer_review=reviewer_review,
        contributor_comment=contributor_comment,
        had_reviewer_review=had_reviewer_review,
        approval_result=approval_result,
    )
