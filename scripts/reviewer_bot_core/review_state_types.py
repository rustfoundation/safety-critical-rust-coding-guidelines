"""Minimal typed review-state structures for the future C1 mutation cutover.

These types cover only the persisted review-entry fields currently needed for:
- review-entry initialization and defaulting
- channel-event acceptance and semantic-key tracking
- reviewer activity updates
- completion marking
- cycle-boundary behavior

They intentionally do not model deferred-gap diagnosis, replay bookkeeping,
approval policy, comment policy, or privileged-command planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AcceptedChannelRecord:
    """Maps to the persisted accepted channel record for non-dismissal events."""

    semantic_key: str
    timestamp: str
    actor: str | None = None
    reviewed_head_sha: str | None = None
    source_precedence: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DismissalAcceptedRecord:
    """Maps to dismissal-only accepted channel records with the current sparse shape."""

    semantic_key: str
    timestamp: str


@dataclass
class ReviewChannelState:
    """Maps to one persisted per-channel map with accepted and seen_keys entries."""

    accepted: AcceptedChannelRecord | DismissalAcceptedRecord | None = None
    seen_keys: list[str] = field(default_factory=list)


@dataclass
class ReviewEntryState:
    """Maps to the persisted review entry fields used by the future C1 cutover.

    Included fields mirror current mutation semantics in `review_state.py` without
    cleaning up persisted names or collapsing precedence behavior.
    """

    skipped: list[str] = field(default_factory=list)
    current_reviewer: str | None = None
    cycle_started_at: str | None = None
    active_cycle_started_at: str | None = None
    assigned_at: str | None = None
    active_head_sha: str | None = None
    last_reviewer_activity: str | None = None
    transition_warning_sent: str | None = None
    transition_notice_sent_at: str | None = None
    assignment_method: str | None = None
    review_completed_at: str | None = None
    review_completed_by: str | None = None
    review_completion_source: str | None = None
    mandatory_approver_required: bool = False
    mandatory_approver_label_applied_at: str | None = None
    mandatory_approver_pinged_at: str | None = None
    mandatory_approver_satisfied_by: str | None = None
    mandatory_approver_satisfied_at: str | None = None
    overdue_anchor: Any | None = None
    reviewer_comment: ReviewChannelState = field(default_factory=ReviewChannelState)
    reviewer_review: ReviewChannelState = field(default_factory=ReviewChannelState)
    contributor_comment: ReviewChannelState = field(default_factory=ReviewChannelState)
    contributor_revision: ReviewChannelState = field(default_factory=ReviewChannelState)
    review_dismissal: ReviewChannelState = field(default_factory=ReviewChannelState)
    current_cycle_completion: dict[str, Any] = field(default_factory=dict)
    current_cycle_write_approval: dict[str, Any] = field(default_factory=dict)
