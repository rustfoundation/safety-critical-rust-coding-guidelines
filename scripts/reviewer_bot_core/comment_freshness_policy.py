"""Direct comment freshness decision policy.

This module owns freshness application decisions only. It does not parse command
syntax, route trust, or perform GitHub writes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentFreshnessDecision:
    kind: str
    channel_name: str | None = None
    semantic_key: str | None = None
    timestamp: str | None = None
    actor: str | None = None
    update_reviewer_activity: bool = False


def decide_comment_freshness(review_data: dict, request) -> CommentFreshnessDecision:
    comment_author = request.comment_author
    created_at = request.comment_created_at
    semantic_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if request.issue_author and request.issue_author.lower() == comment_author.lower():
        return CommentFreshnessDecision(
            kind="accept_channel_event",
            channel_name="contributor_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
            update_reviewer_activity=False,
        )
    current_reviewer = review_data.get("current_reviewer")
    if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():
        return CommentFreshnessDecision(
            kind="accept_channel_event",
            channel_name="reviewer_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
            update_reviewer_activity=True,
        )
    return CommentFreshnessDecision(kind="noop")
