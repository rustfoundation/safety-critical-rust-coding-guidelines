"""Pure status-label projection helpers for reviewer-bot review state."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.reviewer_bot_core.reviewer_response_policy import ReviewerResponseDecision

from .config import (
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
    STATUS_REVIEWER_REASSIGNMENT_NEEDED_LABEL,
)

__all__ = [
    "StatusLabelDelta",
    "StatusLabelProjectionInput",
    "StatusLabelProjectionResult",
    "StatusLabelSyncResult",
    "actual_status_labels_from_snapshot",
    "derive_status_label_projection",
    "desired_labels_from_response_state",
    "desired_status_labels_from_decision",
    "status_label_delta",
    "status_label_projection_output",
]

_SUPPORTED_EMPTY_STATES = frozenset({"done", "closed", "untracked", "no_current_reviewer"})
_BLOCKED_STATES = frozenset({"projection_failed", "live_read_unavailable"})


@dataclass(frozen=True)
class StatusLabelDelta:
    actual_status_labels: tuple[str, ...]
    desired_status_labels: tuple[str, ...]
    labels_to_add: tuple[str, ...]
    labels_to_remove: tuple[str, ...]

    def to_output(self) -> dict[str, object]:
        return {
            "actual_status_labels": sorted(self.actual_status_labels),
            "desired_status_labels": sorted(self.desired_status_labels),
            "labels_to_add": sorted(self.labels_to_add),
            "labels_to_remove": sorted(self.labels_to_remove),
        }


@dataclass(frozen=True)
class StatusLabelProjectionInput:
    issue_number: int
    issue_state: str
    actual_labels: tuple[str, ...]
    reviewer_response: ReviewerResponseDecision
    reviewer_authority_outcome: str
    freshness_runtime_epoch: str | None
    status_projection_epoch: str | None


@dataclass(frozen=True)
class StatusLabelProjectionResult:
    issue_number: int
    response_state: str
    reviewer_authority_outcome: str
    suppression_reason: str | None
    current_scope_key: str | None
    current_scope_basis: str | None
    freshness_runtime_epoch: str | None
    status_projection_epoch: str | None
    delta: StatusLabelDelta
    projection_metadata: dict[str, object]

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "response_state": self.response_state,
            "reviewer_authority_outcome": self.reviewer_authority_outcome,
            "suppression_reason": self.suppression_reason,
            "current_scope_key": self.current_scope_key,
            "current_scope_basis": self.current_scope_basis,
            "freshness_runtime_epoch": self.freshness_runtime_epoch,
            "status_projection_epoch": self.status_projection_epoch,
            "delta": self.delta.to_output(),
            "projection_metadata": dict(self.projection_metadata),
        }


@dataclass(frozen=True)
class StatusLabelSyncResult:
    issue_number: int
    before_status_labels: tuple[str, ...]
    desired_status_labels: tuple[str, ...]
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    changed: bool

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "before_status_labels": sorted(self.before_status_labels),
            "desired_status_labels": sorted(self.desired_status_labels),
            "labels_added": sorted(self.labels_added),
            "labels_removed": sorted(self.labels_removed),
            "changed": self.changed,
        }


def _blocked(reason: str) -> RuntimeError:
    return RuntimeError(f"status_label_projection_blocked:{reason}")


def actual_status_labels_from_snapshot(issue_snapshot: dict) -> tuple[str, ...]:
    labels = issue_snapshot.get("labels") if isinstance(issue_snapshot, dict) else None
    actual: set[str] = set()
    if isinstance(labels, list):
        for label in labels:
            name = label.get("name") if isinstance(label, dict) else label
            if isinstance(name, str) and name.startswith("status: "):
                actual.add(name)
    return tuple(sorted(actual))


def desired_status_labels_from_decision(decision: ReviewerResponseDecision) -> tuple[str, ...]:
    state = getattr(decision, "response_state", None)
    if not isinstance(state, str) or not state.strip():
        raise _blocked("missing_response_state")
    if state in _BLOCKED_STATES:
        raise _blocked(state)
    if state == "awaiting_reviewer_response":
        return (STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,)
    if state == "awaiting_contributor_response":
        return (STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,)
    if state == "awaiting_write_approval":
        return (STATUS_AWAITING_WRITE_APPROVAL_LABEL,)
    if state == "reviewer_reassignment_needed":
        return (STATUS_REVIEWER_REASSIGNMENT_NEEDED_LABEL,)
    if state in _SUPPORTED_EMPTY_STATES:
        return ()
    raise _blocked("unknown_response_state")


def status_label_delta(
    actual_status_labels: tuple[str, ...],
    desired_status_labels: tuple[str, ...],
) -> StatusLabelDelta:
    actual = set(actual_status_labels)
    desired = set(desired_status_labels)
    return StatusLabelDelta(
        actual_status_labels=tuple(sorted(actual)),
        desired_status_labels=tuple(sorted(desired)),
        labels_to_add=tuple(sorted(desired - actual)),
        labels_to_remove=tuple(sorted(actual - desired)),
    )


def derive_status_label_projection(input: StatusLabelProjectionInput) -> StatusLabelProjectionResult:
    issue_state = input.issue_state.strip().lower() if isinstance(input.issue_state, str) else ""
    if issue_state not in {"open", "closed"}:
        raise _blocked("invalid_issue_state")
    decision = input.reviewer_response
    desired = desired_status_labels_from_decision(decision)
    if issue_state == "closed" and desired:
        raise _blocked("closed_issue_with_nonterminal_response")
    delta = status_label_delta(
        tuple(label for label in input.actual_labels if isinstance(label, str) and label.startswith("status: ")),
        desired,
    )
    scope = decision.scope
    return StatusLabelProjectionResult(
        issue_number=input.issue_number,
        response_state=decision.response_state,
        reviewer_authority_outcome=input.reviewer_authority_outcome,
        suppression_reason=decision.suppression_reason,
        current_scope_key=scope.scope_key if scope is not None else None,
        current_scope_basis=scope.scope_basis if scope is not None else None,
        freshness_runtime_epoch=input.freshness_runtime_epoch,
        status_projection_epoch=input.status_projection_epoch,
        delta=delta,
        projection_metadata={
            "source": "reviewer_response_decision",
            "decision_output": decision.to_output(),
        },
    )


def status_label_projection_output(
    result: StatusLabelProjectionResult,
    *,
    preview_action: str,
    validation_nonce: str,
    evaluated_repo: str,
    head_sha: str,
    evaluated_ref: str,
    workflow_path: str,
    run_id: str,
    run_attempt: str,
    artifact_name: str,
    artifact_file: str,
) -> dict[str, object]:
    delta = result.delta.to_output()
    payload: dict[str, object] = {
        "schema_version": 1,
        "preview_action": preview_action,
        "issue_number": result.issue_number,
        "validation_nonce": validation_nonce,
        "evaluated_repo": evaluated_repo,
        "head_sha": head_sha,
        "evaluated_ref": evaluated_ref,
        "workflow_path": workflow_path,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact_name": artifact_name,
        "artifact_file": artifact_file,
        "output_keys": [],
        "freshness_runtime_epoch": result.freshness_runtime_epoch,
        "status_projection_epoch": result.status_projection_epoch,
        "response_state": result.response_state,
        "reviewer_authority_outcome": result.reviewer_authority_outcome,
        "suppression_reason": result.suppression_reason,
        "current_scope_key": result.current_scope_key,
        "current_scope_basis": result.current_scope_basis,
        "actual_status_labels": delta["actual_status_labels"],
        "desired_status_labels": delta["desired_status_labels"],
        "labels_to_add": delta["labels_to_add"],
        "labels_to_remove": delta["labels_to_remove"],
        "projection_metadata": dict(result.projection_metadata),
    }
    payload["output_keys"] = sorted(payload.keys())
    return payload


def desired_labels_from_response_state(
    state_name: str,
    reason: str | None,
) -> tuple[set[str] | None, dict[str, str | None]]:
    from scripts.reviewer_bot_core.reviewer_response_policy import (
        to_reviewer_response_decision,
    )

    try:
        desired = desired_status_labels_from_decision(
            to_reviewer_response_decision({"response_state": state_name, "reason": reason})
        )
    except RuntimeError:
        raise
    return set(desired), {"state": state_name, "reason": reason}
