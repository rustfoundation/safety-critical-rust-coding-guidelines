"""Replay decision policy for deferred workflow_run reconcile.

This module accepts normalized parsed payloads and normalized live-read results.
It does not fetch GitHub objects, inspect workflow files, or mutate review state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObserverNoopDecision:
    source_event_key: str
    reason: str


@dataclass(frozen=True)
class CommentReplayDecision:
    record_source_freshness: bool
    replay_comment_command: bool
    mark_reconciled: bool
    clear_gap: bool
    failed_closed_reason: str | None = None
    diagnostic_summary: str | None = None
    failure_kind: str | None = None
    live_classified: dict | None = None


@dataclass(frozen=True)
class ReviewReplayDecision:
    accept_reviewer_review: bool
    accept_review_dismissal: bool
    replay_timestamp: str | None
    reviewed_head_sha: str | None
    actor_login: str | None
    mark_reconciled: bool
    clear_gap: bool


def decide_observer_noop(*, source_event_key: str, reason: str) -> ObserverNoopDecision:
    return ObserverNoopDecision(source_event_key=source_event_key, reason=reason)


def decide_comment_replay(
    *,
    comment_id: int,
    source_comment_class: str,
    source_has_non_command_text: bool,
    source_freshness_eligible: bool,
    live_comment_found: bool,
    live_body_digest_matches: bool,
    live_classified: dict | None,
    live_failure_kind: str | None,
    runbook_path: str,
) -> CommentReplayDecision:
    if not live_comment_found:
        if live_failure_kind == "not_found":
            summary = (
                f"Deferred comment {comment_id} is no longer visible; source-time freshness only may be preserved. "
                f"See {runbook_path}."
            )
        else:
            summary = (
                f"Deferred comment {comment_id} could not be validated from live GitHub data "
                f"({live_failure_kind or 'unavailable'}); replay suppressed. See {runbook_path}."
            )
        return CommentReplayDecision(
            record_source_freshness=source_freshness_eligible,
            replay_comment_command=False,
            mark_reconciled=False,
            clear_gap=False,
            failed_closed_reason="reconcile_failed_closed",
            diagnostic_summary=summary,
            failure_kind=live_failure_kind,
        )

    if not live_body_digest_matches:
        return CommentReplayDecision(
            record_source_freshness=source_freshness_eligible,
            replay_comment_command=False,
            mark_reconciled=False,
            clear_gap=False,
            failed_closed_reason="reconcile_failed_closed",
            diagnostic_summary=(
                f"Deferred comment {comment_id} body digest changed; command execution suppressed. See {runbook_path}."
            ),
        )

    if live_classified is None:
        raise RuntimeError("Comment replay policy requires live classification when live comment exists")
    live_comment_class = str(live_classified.get("comment_class", ""))
    live_has_non_command_text = bool(live_classified.get("has_non_command_text"))

    if live_comment_class != source_comment_class:
        return CommentReplayDecision(
            record_source_freshness=source_freshness_eligible,
            replay_comment_command=False,
            mark_reconciled=False,
            clear_gap=False,
            failed_closed_reason="reconcile_failed_closed",
            diagnostic_summary=(
                f"Deferred comment {comment_id} classification changed from {source_comment_class} to {live_comment_class}; replay suppressed. See {runbook_path}."
            ),
        )
    if live_has_non_command_text != source_has_non_command_text:
        return CommentReplayDecision(
            record_source_freshness=source_freshness_eligible,
            replay_comment_command=False,
            mark_reconciled=False,
            clear_gap=False,
            failed_closed_reason="reconcile_failed_closed",
            diagnostic_summary=(
                f"Deferred comment {comment_id} non-command text classification drifted; replay suppressed. See {runbook_path}."
            ),
        )
    if source_comment_class in {"command_only", "command_plus_text"} and int(live_classified.get("command_count", 0)) != 1:
        return CommentReplayDecision(
            record_source_freshness=source_freshness_eligible,
            replay_comment_command=False,
            mark_reconciled=False,
            clear_gap=False,
            failed_closed_reason="reconcile_failed_closed",
            diagnostic_summary=(
                f"Deferred comment {comment_id} no longer resolves to exactly one command; replay suppressed. See {runbook_path}."
            ),
        )
    return CommentReplayDecision(
        record_source_freshness=source_freshness_eligible,
        replay_comment_command=source_comment_class in {"command_only", "command_plus_text"},
        mark_reconciled=True,
        clear_gap=True,
        live_classified=live_classified,
    )


def decide_review_submitted_replay(
    *,
    source_event_key: str,
    actor_login: str,
    current_reviewer: str | None,
    live_commit_id: str | None,
    live_submitted_at: str | None,
) -> ReviewReplayDecision:
    actor_matches = isinstance(current_reviewer, str) and current_reviewer.lower() == actor_login.lower()
    accept_reviewer_review = actor_matches and isinstance(live_commit_id, str) and isinstance(live_submitted_at, str)
    return ReviewReplayDecision(
        accept_reviewer_review=accept_reviewer_review,
        accept_review_dismissal=False,
        replay_timestamp=live_submitted_at,
        reviewed_head_sha=live_commit_id,
        actor_login=actor_login,
        mark_reconciled=True,
        clear_gap=True,
    )


def decide_review_dismissed_replay(*, source_event_key: str, timestamp: str) -> ReviewReplayDecision:
    return ReviewReplayDecision(
        accept_reviewer_review=False,
        accept_review_dismissal=True,
        replay_timestamp=timestamp,
        reviewed_head_sha=None,
        actor_login=None,
        mark_reconciled=True,
        clear_gap=True,
    )
