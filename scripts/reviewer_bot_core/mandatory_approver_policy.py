"""Mandatory-approver decision owner.

Future changes that belong here:
- mandatory-approver escalation decisions from stored review state and already-read collaborator outcomes
- mandatory-approver satisfaction decisions from stored review state and caller-supplied approver identity

Future changes that do not belong here:
- label writes, comment posts, or direct state mutation
- reviewer-response derivation

Old module no longer preferred for these mandatory-approver decision changes:
- scripts/reviewer_bot_lib/reviews.py
"""

from __future__ import annotations


def decide_mandatory_approver_escalation(review_data: dict, *, now: str, label_exists: bool) -> dict[str, object]:
    require_escalation = not review_data.get("mandatory_approver_required")
    return {
        "allow": True,
        "require_escalation": require_escalation,
        "clear_satisfaction": require_escalation,
        "attempt_label_apply": bool(label_exists),
        "record_label_applied_at": bool(label_exists) and review_data.get("mandatory_approver_label_applied_at") is None,
        "post_ping": review_data.get("mandatory_approver_pinged_at") is None,
        "now": now,
    }


def decide_mandatory_approver_satisfaction(review_data: dict, *, approver: str, now: str) -> dict[str, object]:
    if not review_data.get("mandatory_approver_required"):
        return {"allow": False}
    if review_data.get("mandatory_approver_satisfied_at"):
        return {"allow": False}
    return {
        "allow": True,
        "approver": approver,
        "now": now,
        "attempt_label_remove": True,
        "post_comment": True,
    }
