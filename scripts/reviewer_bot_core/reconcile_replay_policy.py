"""Replay decision policy for deferred workflow_run reconcile.

This module accepts normalized parsed payloads and normalized live-read results.
It does not fetch GitHub objects, inspect workflow files, or mutate review state.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    diagnostic_reason: str | None = None
    failure_kind: str | None = None


@dataclass(frozen=True)
class DismissedReviewReplayPlan:
    record_channel_event: bool
    rebuild_live_approval: bool
    mark_reconciled: bool
    clear_gap: bool
    replay_timestamp: str | None
    diagnostic_reason: str | None
    failure_kind: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "record_channel_event": self.record_channel_event,
            "rebuild_live_approval": self.rebuild_live_approval,
            "mark_reconciled": self.mark_reconciled,
            "clear_gap": self.clear_gap,
            "replay_timestamp": self.replay_timestamp,
            "diagnostic_reason": self.diagnostic_reason,
            "failure_kind": self.failure_kind,
        }


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
    actor_login: str | None,
    current_reviewer: str | None,
    live_commit_id: str | None,
    live_submitted_at: str | None,
    current_head_sha: str | None = None,
    live_state: str | None = None,
    live_visibility_status: str | None = "visible",
    replay_allowed: bool = True,
) -> ReviewReplayDecision:
    del source_event_key
    state = live_state.upper() if isinstance(live_state, str) else None
    allowed_state = state in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
    actor_key = actor_login.strip().lower() if isinstance(actor_login, str) else ""
    current_reviewer_key = current_reviewer.strip().lower() if isinstance(current_reviewer, str) else ""
    actor_matches = bool(actor_key and current_reviewer_key and actor_key == current_reviewer_key)
    required_inputs_available = all(
        isinstance(value, str) and value.strip()
        for value in (actor_login, current_reviewer, live_commit_id, live_submitted_at, current_head_sha)
    )
    live_visible = live_visibility_status == "visible"
    current_head_matches = isinstance(live_commit_id, str) and isinstance(current_head_sha, str) and live_commit_id == current_head_sha
    if not replay_allowed:
        return ReviewReplayDecision(
            accept_reviewer_review=False,
            accept_review_dismissal=False,
            replay_timestamp=None,
            reviewed_head_sha=None,
            actor_login=actor_login,
            mark_reconciled=False,
            clear_gap=False,
            diagnostic_reason="submitted_review_replay_not_admitted",
            failure_kind="replay_not_admitted",
        )
    if not required_inputs_available:
        return ReviewReplayDecision(
            accept_reviewer_review=False,
            accept_review_dismissal=False,
            replay_timestamp=None,
            reviewed_head_sha=None,
            actor_login=actor_login,
            mark_reconciled=False,
            clear_gap=False,
            diagnostic_reason="submitted_review_semantic_inputs_missing",
            failure_kind="semantic_inputs_missing",
        )
    if not live_visible or not allowed_state or not current_head_matches or not actor_matches:
        reason = "submitted_review_live_observation_untrusted"
        if not current_head_matches:
            failure_kind = "stale_head"
        elif not allowed_state:
            failure_kind = "unsupported_review_state"
        elif not actor_matches:
            failure_kind = "actor_mismatch"
        else:
            failure_kind = "live_review_untrusted"
        return ReviewReplayDecision(
            accept_reviewer_review=False,
            accept_review_dismissal=False,
            replay_timestamp=None,
            reviewed_head_sha=None,
            actor_login=actor_login,
            mark_reconciled=False,
            clear_gap=False,
            diagnostic_reason=reason,
            failure_kind=failure_kind,
        )
    return ReviewReplayDecision(
        accept_reviewer_review=True,
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


def decide_review_dismissed_replay_plan(
    *,
    source_event_key: str,
    dismissal_timestamp: str | None,
    dismissal_exact: bool,
    live_pr_readable: bool,
) -> DismissedReviewReplayPlan:
    del source_event_key
    if not live_pr_readable:
        return DismissedReviewReplayPlan(
            record_channel_event=False,
            rebuild_live_approval=False,
            mark_reconciled=False,
            clear_gap=False,
            replay_timestamp=None,
            diagnostic_reason="live_pr_unreadable",
            failure_kind="live_pr_unreadable",
        )
    if not dismissal_exact or not isinstance(dismissal_timestamp, str) or not dismissal_timestamp.strip():
        return DismissedReviewReplayPlan(
            record_channel_event=False,
            rebuild_live_approval=True,
            mark_reconciled=False,
            clear_gap=False,
            replay_timestamp=None,
            diagnostic_reason="dismissal_time_not_exact",
            failure_kind="dismissal_time_unavailable",
        )
    return DismissedReviewReplayPlan(
        record_channel_event=True,
        rebuild_live_approval=True,
        mark_reconciled=True,
        clear_gap=True,
        replay_timestamp=dismissal_timestamp,
        diagnostic_reason=None,
        failure_kind=None,
    )
