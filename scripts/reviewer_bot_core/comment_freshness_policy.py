"""Direct comment freshness decision policy.

This module owns freshness application decisions only. It does not parse command
syntax, route trust, or perform GitHub writes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentFreshnessEvent:
    issue_number: int
    is_pull_request: bool
    source_event_key: str
    comment_id: int
    actor: str
    created_at: str
    channel_kind: str
    source_kind: str
    reviewed_head_sha: str | None
    issue_author: str
    current_reviewer: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "is_pull_request": self.is_pull_request,
            "source_event_key": self.source_event_key,
            "comment_id": self.comment_id,
            "actor": self.actor,
            "created_at": self.created_at,
            "channel_kind": self.channel_kind,
            "source_kind": self.source_kind,
            "reviewed_head_sha": self.reviewed_head_sha,
            "issue_author": self.issue_author,
            "current_reviewer": self.current_reviewer,
        }


@dataclass(frozen=True)
class CommentFreshnessDecision:
    kind: str
    channel_name: str | None = None
    semantic_key: str | None = None
    timestamp: str | None = None
    actor: str | None = None
    update_reviewer_activity: bool = False
    diagnostic_reason: str | None = None

    def to_output(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "channel_name": self.channel_name,
            "semantic_key": self.semantic_key,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "update_reviewer_activity": self.update_reviewer_activity,
            "diagnostic_reason": self.diagnostic_reason,
        }


def build_comment_freshness_event(review_data: dict, request) -> CommentFreshnessEvent:
    source_kind = getattr(request, "comment_source_kind", "issue_comment") or "issue_comment"
    channel_kind = "review_comment" if source_kind == "pull_request_review_comment" else "issue_thread"
    return CommentFreshnessEvent(
        issue_number=int(request.issue_number),
        is_pull_request=bool(request.is_pull_request),
        source_event_key=request.comment_source_event_key or f"{source_kind}:{request.comment_id}",
        comment_id=int(request.comment_id),
        actor=str(request.comment_author),
        created_at=str(request.comment_created_at),
        channel_kind=channel_kind,
        source_kind=str(source_kind),
        reviewed_head_sha=getattr(request, "reviewed_head_sha", None),
        issue_author=str(request.issue_author),
        current_reviewer=review_data.get("current_reviewer") if isinstance(review_data.get("current_reviewer"), str) else None,
    )


def _same_login(left: str | None, right: str | None) -> bool:
    return isinstance(left, str) and isinstance(right, str) and bool(left.strip()) and left.lower() == right.lower()


def decide_comment_freshness_event(
    event: CommentFreshnessEvent,
    *,
    current_head_sha: str | None,
) -> CommentFreshnessDecision:
    if event.source_kind not in {"issue_comment", "pull_request_review_comment"}:
        return CommentFreshnessDecision(kind="blocked", diagnostic_reason="unsupported_comment_source_kind")
    if event.channel_kind not in {"issue_thread", "review_comment"}:
        return CommentFreshnessDecision(kind="blocked", diagnostic_reason="unsupported_comment_channel_kind")

    if event.source_kind == "pull_request_review_comment":
        if not event.reviewed_head_sha:
            return CommentFreshnessDecision(kind="diagnostic_only", diagnostic_reason="missing_reviewed_head_sha")
        if current_head_sha and event.reviewed_head_sha != current_head_sha:
            return CommentFreshnessDecision(kind="diagnostic_only", diagnostic_reason="stale_reviewed_head_sha")
        if _same_login(event.issue_author, event.actor):
            return CommentFreshnessDecision(
                kind="accept_channel_event",
                channel_name="contributor_comment",
                semantic_key=event.source_event_key,
                timestamp=event.created_at,
                actor=event.actor,
                update_reviewer_activity=False,
            )
        return CommentFreshnessDecision(kind="diagnostic_only", diagnostic_reason="review_comments_do_not_suppress_reminders")

    if _same_login(event.issue_author, event.actor):
        return CommentFreshnessDecision(
            kind="accept_channel_event",
            channel_name="contributor_comment",
            semantic_key=event.source_event_key,
            timestamp=event.created_at,
            actor=event.actor,
            update_reviewer_activity=False,
        )
    if _same_login(event.current_reviewer, event.actor):
        if event.is_pull_request:
            return CommentFreshnessDecision(
                kind="diagnostic_only",
                semantic_key=event.source_event_key,
                timestamp=event.created_at,
                actor=event.actor,
                update_reviewer_activity=False,
                diagnostic_reason="plain_pr_reviewer_comment_is_diagnostic_only",
            )
        return CommentFreshnessDecision(
            kind="accept_channel_event",
            channel_name="reviewer_comment",
            semantic_key=event.source_event_key,
            timestamp=event.created_at,
            actor=event.actor,
            update_reviewer_activity=True,
        )
    return CommentFreshnessDecision(kind="noop")


def decide_comment_freshness(review_data: dict, request) -> CommentFreshnessDecision:
    event = build_comment_freshness_event(review_data, request)
    current_head_sha = review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None
    return decide_comment_freshness_event(event, current_head_sha=current_head_sha)
