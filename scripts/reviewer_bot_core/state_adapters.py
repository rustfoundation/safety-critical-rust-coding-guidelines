"""Adapters between persisted review-entry dicts and minimal core review-state types.

These adapters are limited to the mutable review-state fields needed for the C1
cutover. They preserve current compatibility-upgrade behavior for sparse review
entries without introducing schema cleanup.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .review_state_types import (
    AcceptedChannelRecord,
    DismissalAcceptedRecord,
    ReviewChannelState,
    ReviewEntryState,
)


def _channel_from_persisted(review_entry: dict[str, Any], name: str) -> ReviewChannelState:
    raw_channel = review_entry.get(name)
    if not isinstance(raw_channel, dict):
        return ReviewChannelState()

    accepted = raw_channel.get("accepted")
    typed_accepted: AcceptedChannelRecord | DismissalAcceptedRecord | None
    if not isinstance(accepted, dict):
        typed_accepted = None
    elif set(accepted).issubset({"semantic_key", "timestamp"}):
        typed_accepted = DismissalAcceptedRecord(
            semantic_key=str(accepted.get("semantic_key", "")),
            timestamp=str(accepted.get("timestamp", "")),
        )
    else:
        typed_accepted = AcceptedChannelRecord(
            semantic_key=str(accepted.get("semantic_key", "")),
            timestamp=str(accepted.get("timestamp", "")),
            actor=(str(accepted["actor"]) if accepted.get("actor") is not None else None),
            reviewed_head_sha=(
                str(accepted["reviewed_head_sha"])
                if accepted.get("reviewed_head_sha") is not None
                else None
            ),
            source_precedence=int(accepted.get("source_precedence", 0)),
            payload=deepcopy(accepted.get("payload") or {}),
        )

    seen_keys = raw_channel.get("seen_keys")
    return ReviewChannelState(
        accepted=typed_accepted,
        seen_keys=list(seen_keys) if isinstance(seen_keys, list) else [],
    )


def _channel_to_persisted(channel: ReviewChannelState) -> dict[str, Any]:
    accepted = channel.accepted
    if isinstance(accepted, AcceptedChannelRecord):
        persisted_accepted: dict[str, Any] | None = {
            "semantic_key": accepted.semantic_key,
            "timestamp": accepted.timestamp,
            "actor": accepted.actor,
            "reviewed_head_sha": accepted.reviewed_head_sha,
            "source_precedence": accepted.source_precedence,
            "payload": deepcopy(accepted.payload),
        }
    elif isinstance(accepted, DismissalAcceptedRecord):
        persisted_accepted = {
            "semantic_key": accepted.semantic_key,
            "timestamp": accepted.timestamp,
        }
    else:
        persisted_accepted = None
    return {
        "accepted": persisted_accepted,
        "seen_keys": list(channel.seen_keys),
    }


def review_entry_from_persisted(review_entry: dict[str, Any] | list[Any] | None) -> ReviewEntryState | None:
    if review_entry is None:
        return None
    if isinstance(review_entry, list):
        review_entry = {"skipped": list(review_entry)}
    if not isinstance(review_entry, dict):
        return None

    skipped = review_entry.get("skipped")
    return ReviewEntryState(
        skipped=list(skipped) if isinstance(skipped, list) else [],
        current_reviewer=(str(review_entry["current_reviewer"]) if review_entry.get("current_reviewer") is not None else None),
        cycle_started_at=(str(review_entry["cycle_started_at"]) if review_entry.get("cycle_started_at") is not None else None),
        active_cycle_started_at=(
            str(review_entry["active_cycle_started_at"])
            if review_entry.get("active_cycle_started_at") is not None
            else None
        ),
        assigned_at=(str(review_entry["assigned_at"]) if review_entry.get("assigned_at") is not None else None),
        active_head_sha=(str(review_entry["active_head_sha"]) if review_entry.get("active_head_sha") is not None else None),
        last_reviewer_activity=(
            str(review_entry["last_reviewer_activity"])
            if review_entry.get("last_reviewer_activity") is not None
            else None
        ),
        transition_warning_sent=(
            str(review_entry["transition_warning_sent"])
            if review_entry.get("transition_warning_sent") is not None
            else None
        ),
        transition_notice_sent_at=(
            str(review_entry["transition_notice_sent_at"])
            if review_entry.get("transition_notice_sent_at") is not None
            else None
        ),
        assignment_method=(str(review_entry["assignment_method"]) if review_entry.get("assignment_method") is not None else None),
        review_completed_at=(
            str(review_entry["review_completed_at"])
            if review_entry.get("review_completed_at") is not None
            else None
        ),
        review_completed_by=(
            str(review_entry["review_completed_by"])
            if review_entry.get("review_completed_by") is not None
            else None
        ),
        review_completion_source=(
            str(review_entry["review_completion_source"])
            if review_entry.get("review_completion_source") is not None
            else None
        ),
        mandatory_approver_required=bool(review_entry.get("mandatory_approver_required", False)),
        mandatory_approver_label_applied_at=(
            str(review_entry["mandatory_approver_label_applied_at"])
            if review_entry.get("mandatory_approver_label_applied_at") is not None
            else None
        ),
        mandatory_approver_pinged_at=(
            str(review_entry["mandatory_approver_pinged_at"])
            if review_entry.get("mandatory_approver_pinged_at") is not None
            else None
        ),
        mandatory_approver_satisfied_by=(
            str(review_entry["mandatory_approver_satisfied_by"])
            if review_entry.get("mandatory_approver_satisfied_by") is not None
            else None
        ),
        mandatory_approver_satisfied_at=(
            str(review_entry["mandatory_approver_satisfied_at"])
            if review_entry.get("mandatory_approver_satisfied_at") is not None
            else None
        ),
        overdue_anchor=deepcopy(review_entry.get("overdue_anchor")),
        reviewer_comment=_channel_from_persisted(review_entry, "reviewer_comment"),
        reviewer_review=_channel_from_persisted(review_entry, "reviewer_review"),
        contributor_comment=_channel_from_persisted(review_entry, "contributor_comment"),
        contributor_revision=_channel_from_persisted(review_entry, "contributor_revision"),
        review_dismissal=_channel_from_persisted(review_entry, "review_dismissal"),
        current_cycle_completion=deepcopy(review_entry.get("current_cycle_completion") or {})
        if isinstance(review_entry.get("current_cycle_completion"), dict)
        else {},
        current_cycle_write_approval=deepcopy(review_entry.get("current_cycle_write_approval") or {})
        if isinstance(review_entry.get("current_cycle_write_approval"), dict)
        else {},
    )


def review_entry_to_persisted(review_entry: ReviewEntryState) -> dict[str, Any]:
    return {
        "skipped": list(review_entry.skipped),
        "current_reviewer": review_entry.current_reviewer,
        "cycle_started_at": review_entry.cycle_started_at,
        "active_cycle_started_at": review_entry.active_cycle_started_at,
        "assigned_at": review_entry.assigned_at,
        "active_head_sha": review_entry.active_head_sha,
        "last_reviewer_activity": review_entry.last_reviewer_activity,
        "transition_warning_sent": review_entry.transition_warning_sent,
        "transition_notice_sent_at": review_entry.transition_notice_sent_at,
        "assignment_method": review_entry.assignment_method,
        "review_completed_at": review_entry.review_completed_at,
        "review_completed_by": review_entry.review_completed_by,
        "review_completion_source": review_entry.review_completion_source,
        "mandatory_approver_required": review_entry.mandatory_approver_required,
        "mandatory_approver_label_applied_at": review_entry.mandatory_approver_label_applied_at,
        "mandatory_approver_pinged_at": review_entry.mandatory_approver_pinged_at,
        "mandatory_approver_satisfied_by": review_entry.mandatory_approver_satisfied_by,
        "mandatory_approver_satisfied_at": review_entry.mandatory_approver_satisfied_at,
        "overdue_anchor": deepcopy(review_entry.overdue_anchor),
        "reviewer_comment": _channel_to_persisted(review_entry.reviewer_comment),
        "reviewer_review": _channel_to_persisted(review_entry.reviewer_review),
        "contributor_comment": _channel_to_persisted(review_entry.contributor_comment),
        "contributor_revision": _channel_to_persisted(review_entry.contributor_revision),
        "review_dismissal": _channel_to_persisted(review_entry.review_dismissal),
        "current_cycle_completion": deepcopy(review_entry.current_cycle_completion),
        "current_cycle_write_approval": deepcopy(review_entry.current_cycle_write_approval),
    }


def apply_local_state_core_to_persisted(target: dict[str, Any], review_entry: ReviewEntryState) -> dict[str, Any]:
    persisted = review_entry_to_persisted(review_entry)
    for key, value in persisted.items():
        target[key] = value
    return target
