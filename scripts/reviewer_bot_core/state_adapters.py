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

_CANONICAL_REPAIR_MARKERS = (
    "review_repair",
    "head_observation_repair",
    "status_label_projection",
)

_DEFERRED_GAP_MIGRATION_DROP_KEYS = {
    "source_run_id",
    "source_run_attempt",
    "source_workflow_file",
    "source_artifact_name",
}


def _migrate_repair_marker(marker: Any) -> dict[str, Any] | None:
    if not isinstance(marker, dict):
        return None
    return {
        "kind": marker.get("kind"),
        "reason": marker.get("reason"),
        "failure_kind": marker.get("failure_kind"),
        "recorded_at": marker.get("recorded_at"),
    }


def _migrate_deferred_gaps(legacy: Any) -> dict[str, Any]:
    if not isinstance(legacy, dict):
        return {}
    migrated: dict[str, Any] = {}
    for source_event_key, payload in legacy.items():
        if not isinstance(source_event_key, str) or not isinstance(payload, dict):
            continue
        migrated[source_event_key] = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in _DEFERRED_GAP_MIGRATION_DROP_KEYS
        }
    return migrated


def _migrate_reconciled_source_events(legacy: Any) -> dict[str, Any]:
    if isinstance(legacy, dict):
        migrated: dict[str, Any] = {}
        for source_event_key, record in legacy.items():
            if not isinstance(source_event_key, str):
                continue
            if isinstance(record, dict):
                migrated[source_event_key] = {
                    "source_event_key": str(record.get("source_event_key") or source_event_key),
                    "reconciled_at": record.get("reconciled_at"),
                }
            else:
                migrated[source_event_key] = {
                    "source_event_key": source_event_key,
                    "reconciled_at": None,
                }
        return migrated
    if isinstance(legacy, list):
        return {
            source_event_key: {"source_event_key": source_event_key, "reconciled_at": None}
            for source_event_key in legacy
            if isinstance(source_event_key, str)
        }
    return {}


def ensure_sidecar_subtree(review_entry: dict[str, Any], *, state_last_updated: str | None = None) -> None:
    del state_last_updated
    sidecars = review_entry.get("sidecars")
    if not isinstance(sidecars, dict):
        sidecars = {}
        review_entry["sidecars"] = sidecars

    sidecars["pending_privileged_commands"] = (
        deepcopy(sidecars.get("pending_privileged_commands"))
        if isinstance(sidecars.get("pending_privileged_commands"), dict)
        else deepcopy(review_entry.get("pending_privileged_commands"))
        if isinstance(review_entry.get("pending_privileged_commands"), dict)
        else {}
    )
    sidecars["deferred_gaps"] = (
        deepcopy(sidecars.get("deferred_gaps"))
        if isinstance(sidecars.get("deferred_gaps"), dict)
        else _migrate_deferred_gaps(review_entry.get("deferred_gaps"))
    )
    sidecars["observer_discovery_watermarks"] = (
        deepcopy(sidecars.get("observer_discovery_watermarks"))
        if isinstance(sidecars.get("observer_discovery_watermarks"), dict)
        else deepcopy(review_entry.get("observer_discovery_watermarks"))
        if isinstance(review_entry.get("observer_discovery_watermarks"), dict)
        else {}
    )
    sidecars["reconciled_source_events"] = _migrate_reconciled_source_events(
        sidecars.get("reconciled_source_events")
        if sidecars.get("reconciled_source_events") is not None
        else review_entry.get("reconciled_source_events")
    )

    repair_markers = sidecars.get("repair_markers") if isinstance(sidecars.get("repair_markers"), dict) else {}
    canonical_repair_markers = dict.fromkeys(_CANONICAL_REPAIR_MARKERS)
    for key in _CANONICAL_REPAIR_MARKERS:
        if isinstance(repair_markers.get(key), dict):
            canonical_repair_markers[key] = _migrate_repair_marker(repair_markers[key])

    legacy_marker = review_entry.get("repair_needed")
    if isinstance(legacy_marker, dict):
        migrated = _migrate_repair_marker(legacy_marker)
        if legacy_marker.get("kind") == "projection_failure":
            canonical_repair_markers["status_label_projection"] = migrated
        elif legacy_marker.get("phase") == "review_repair":
            canonical_repair_markers["review_repair"] = migrated
        elif legacy_marker.get("phase") == "head_observation_repair":
            canonical_repair_markers["head_observation_repair"] = migrated
    sidecars["repair_markers"] = canonical_repair_markers

    for legacy_key in (
        "repair_needed",
        "pending_privileged_commands",
        "deferred_gaps",
        "observer_discovery_watermarks",
        "reconciled_source_events",
    ):
        review_entry.pop(legacy_key, None)


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
