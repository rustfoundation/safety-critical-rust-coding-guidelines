"""Pure projection helpers for reviewer-bot review state."""

from __future__ import annotations

from .config import (
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
)

__all__ = [
    "desired_labels_from_response_state",
]


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
