"""Issue 314 state-health preview and repair contracts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from scripts.reviewer_bot_core.reviewer_response_policy import (
    ReviewerResponseDecision,
    to_reviewer_response_decision,
)

from . import overdue, reviews
from .reminder_comments import ReminderCommentScan, scan_reviewer_reminder_comments
from .reviews_projection import (
    StatusLabelProjectionResult,
    actual_status_labels_from_snapshot,
)

_REQUIRED_IDENTITY_FIELDS = (
    "validation_nonce",
    "evaluated_repo",
    "head_sha",
    "evaluated_ref",
    "workflow_path",
    "run_id",
    "run_attempt",
)
_SUPPORTED_ACTION_WORKFLOWS = {
    "preview-issue314-state-health": ".github/workflows/reviewer-bot-preview.yml",
    "repair-issue314-state-health": ".github/workflows/reviewer-bot-sweeper-repair.yml",
}
_SUPPORTED_REPAIR_RESULTS = frozenset({"already_healthy", "changed", "blocked"})


def _missing_identity_fields(values: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in _REQUIRED_IDENTITY_FIELDS
            if not isinstance(values.get(name), str) or not str(values.get(name)).strip()
        )
    )


def _require_identity(values: dict[str, object], *, reason: str) -> None:
    missing = _missing_identity_fields(values)
    if missing:
        raise RuntimeError(f"issue314_state_health_identity_blocked:{reason}:" + ",".join(missing))


def _require_request_identity(request: "Issue314StateHealthRepairRequest") -> None:
    expected_workflow = _SUPPORTED_ACTION_WORKFLOWS.get(request.repair_action)
    if expected_workflow is None:
        raise RuntimeError("issue314_state_health_request_blocked:unsupported_action")
    _require_identity(request.__dict__, reason="missing")
    if request.workflow_path != expected_workflow:
        raise RuntimeError("issue314_state_health_request_blocked:workflow_path")


def _require_repair_summary_contract(summary: "Issue314StateHealthRepairSummary") -> None:
    _require_identity(summary.__dict__, reason="missing")
    if summary.target_collection_mode != "global_issue314_state_health":
        raise RuntimeError("issue314_state_health_repair_summary_blocked:target_collection_mode")
    if summary.result not in _SUPPORTED_REPAIR_RESULTS:
        raise RuntimeError("issue314_state_health_repair_summary_blocked:result")
    if summary.reviewer_facing_reminder_posts_attempted != 0:
        raise RuntimeError("issue314_state_health_repair_summary_blocked:reviewer_reminder_attempt")
    if summary.manual_issue314_edit_status != "not_attempted":
        raise RuntimeError("issue314_state_health_repair_summary_blocked:manual_issue314_edit")
    if summary.rows_blocked and summary.result != "blocked":
        raise RuntimeError("issue314_state_health_repair_summary_blocked:blocked_rows_success")
    if set(summary.status_labels_changed) - set(summary.rows_repaired):
        raise RuntimeError("issue314_state_health_repair_summary_blocked:final_label_only_status")
    if summary.result == "already_healthy" and (
        summary.rows_repaired or summary.rows_removed_closed or summary.status_labels_changed
    ):
        raise RuntimeError("issue314_state_health_repair_summary_blocked:changed_rows_marked_healthy")


@dataclass(frozen=True)
class Issue314StateHealthClassificationInput:
    state_issue_number: int
    validation_nonce: str
    active_review_rows: tuple[dict[str, object], ...]
    live_snapshots: dict[int, dict[str, object]]
    reviewer_responses: dict[int, ReviewerResponseDecision]
    status_projections: dict[int, StatusLabelProjectionResult]
    reminder_scans: dict[int, ReminderCommentScan | None]
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str


@dataclass(frozen=True)
class Issue314StateHealthRepairRequest:
    repair_action: str
    state_issue_number: int
    validation_nonce: str
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str


@dataclass(frozen=True)
class Issue314StateHealthRow:
    issue_number: int
    current_reviewer: str | None
    active_head_sha: str | None
    live_state: str | None
    is_pull_request: bool
    live_head_sha: str | None
    live_status_labels: tuple[str, ...]
    reviewer_response: dict[str, object]
    status_projection: dict[str, object]
    reminder_scan: dict[str, object] | None
    health_classification: str
    repair_outcome: str
    classification_reason: str
    status_label_risk: str
    automated_reminder_risk: bool | None
    blockers: tuple[str, ...]

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "current_reviewer": self.current_reviewer,
            "active_head_sha": self.active_head_sha,
            "live_state": self.live_state,
            "is_pull_request": self.is_pull_request,
            "live_head_sha": self.live_head_sha,
            "live_status_labels": sorted(self.live_status_labels),
            "reviewer_response": dict(self.reviewer_response),
            "status_projection": dict(self.status_projection),
            "reminder_scan": self.reminder_scan,
            "health_classification": self.health_classification,
            "repair_outcome": self.repair_outcome,
            "classification_reason": self.classification_reason,
            "status_label_risk": self.status_label_risk,
            "automated_reminder_risk": self.automated_reminder_risk,
            "blockers": sorted(self.blockers),
        }


@dataclass(frozen=True)
class Issue314StateHealthSummary:
    schema_version: int
    preview_action: str
    state_issue_number: int
    issue_number: int
    validation_nonce: str
    active_review_row_count: int
    active_rows_inspected: tuple[int, ...]
    row_inventory: tuple[Issue314StateHealthRow, ...]
    row_health_summary: dict[str, int]
    status_projection_summary: dict[str, object]
    rows_repairable: tuple[int, ...]
    rows_operator_action_required: tuple[int, ...]
    rows_blocked: tuple[int, ...]
    pr264_no_ping_status: str
    lock_attempted: bool
    state_save_attempted: bool
    tracked_state_mutations_attempted: bool
    touched_projection_attempted: bool
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str
    artifact_name: str
    artifact_file: str
    output_keys: tuple[str, ...]

    def to_output(self) -> dict[str, object]:
        _require_identity(self.__dict__, reason="preview_output")
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "preview_action": self.preview_action,
            "state_issue_number": self.state_issue_number,
            "issue_number": self.issue_number,
            "validation_nonce": self.validation_nonce,
            "active_review_row_count": self.active_review_row_count,
            "active_rows_inspected": sorted(self.active_rows_inspected),
            "row_inventory": [
                row.to_output()
                for row in sorted(self.row_inventory, key=lambda item: item.issue_number)
            ],
            "row_health_summary": dict(self.row_health_summary),
            "status_projection_summary": dict(self.status_projection_summary),
            "rows_repairable": sorted(self.rows_repairable),
            "rows_operator_action_required": sorted(self.rows_operator_action_required),
            "rows_blocked": sorted(self.rows_blocked),
            "pr264_no_ping_status": self.pr264_no_ping_status,
            "lock_attempted": self.lock_attempted,
            "state_save_attempted": self.state_save_attempted,
            "tracked_state_mutations_attempted": self.tracked_state_mutations_attempted,
            "touched_projection_attempted": self.touched_projection_attempted,
            "evaluated_repo": self.evaluated_repo,
            "head_sha": self.head_sha,
            "evaluated_ref": self.evaluated_ref,
            "workflow_path": self.workflow_path,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_name": self.artifact_name,
            "artifact_file": self.artifact_file,
            "output_keys": [],
        }
        payload["output_keys"] = sorted(payload.keys())
        return payload


@dataclass(frozen=True)
class Issue314StateHealthRepairSummary:
    schema_version: int
    repair_action: str
    state_issue_number: int
    issue_number: int
    validation_nonce: str
    target_collection_mode: str
    active_rows_inspected: tuple[int, ...]
    rows_repaired: tuple[int, ...]
    rows_removed_closed: tuple[int, ...]
    rows_operator_action_required: tuple[int, ...]
    rows_blocked: tuple[int, ...]
    status_labels_changed: tuple[int, ...]
    reviewer_facing_reminder_posts_attempted: int
    manual_issue314_edit_status: str
    state_store_mutation_mode: str
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str
    artifact_name: str
    artifact_file: str
    output_keys: tuple[str, ...]
    result: str

    def to_output(self) -> dict[str, object]:
        _require_repair_summary_contract(self)
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "repair_action": self.repair_action,
            "state_issue_number": self.state_issue_number,
            "issue_number": self.issue_number,
            "validation_nonce": self.validation_nonce,
            "target_collection_mode": self.target_collection_mode,
            "active_rows_inspected": sorted(self.active_rows_inspected),
            "rows_repaired": sorted(self.rows_repaired),
            "rows_removed_closed": sorted(self.rows_removed_closed),
            "rows_operator_action_required": sorted(self.rows_operator_action_required),
            "rows_blocked": sorted(self.rows_blocked),
            "status_labels_changed": sorted(self.status_labels_changed),
            "reviewer_facing_reminder_posts_attempted": self.reviewer_facing_reminder_posts_attempted,
            "manual_issue314_edit_status": self.manual_issue314_edit_status,
            "state_store_mutation_mode": self.state_store_mutation_mode,
            "evaluated_repo": self.evaluated_repo,
            "head_sha": self.head_sha,
            "evaluated_ref": self.evaluated_ref,
            "workflow_path": self.workflow_path,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_name": self.artifact_name,
            "artifact_file": self.artifact_file,
            "output_keys": [],
            "result": self.result,
        }
        payload["output_keys"] = sorted(payload.keys())
        return payload


def _config(bot, name: str, default: str = "") -> str:
    return bot.get_config_value(name, default).strip()


def _default_request(bot) -> Issue314StateHealthRepairRequest:
    run_id = _config(bot, "GITHUB_RUN_ID") or _config(bot, "WORKFLOW_RUN_ID")
    run_attempt = _config(bot, "GITHUB_RUN_ATTEMPT") or "1"
    head_sha = _config(bot, "HEAD_SHA") or _config(bot, "GITHUB_SHA")
    return Issue314StateHealthRepairRequest(
        repair_action=_config(bot, "MANUAL_ACTION") or "preview-issue314-state-health",
        state_issue_number=bot.state_issue_number(),
        validation_nonce=_config(bot, "VALIDATION_NONCE"),
        evaluated_repo=_config(bot, "EVALUATED_REPO") or _config(bot, "GITHUB_REPOSITORY"),
        head_sha=head_sha,
        evaluated_ref=_config(bot, "EVALUATED_REF") or head_sha,
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id=run_id,
        run_attempt=run_attempt,
    )


def _artifact_name(prefix: str, request: Issue314StateHealthRepairRequest) -> str:
    return f"{prefix}-{request.run_id}-attempt-{request.run_attempt}"


def _active_rows(state: dict) -> tuple[dict[str, object], ...]:
    active_reviews = state.get("active_reviews") if isinstance(state, dict) else None
    if not isinstance(active_reviews, dict):
        return ()
    rows: list[dict[str, object]] = []
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        try:
            issue_number = int(issue_key)
        except (TypeError, ValueError):
            continue
        if issue_number > 0:
            rows.append({"issue_number": issue_number, "review_data": review_data})
    return tuple(sorted(rows, key=lambda row: int(row["issue_number"])))


def _comment_scan(bot, issue_number: int) -> ReminderCommentScan | None:
    try:
        response = bot.github.list_issue_comments_result(issue_number, page=1)
    except (AssertionError, AttributeError, RuntimeError):
        return None
    if not response.ok or not isinstance(response.payload, list):
        return None
    return scan_reviewer_reminder_comments(response.payload)


def _closed_decision(issue_number: int) -> ReviewerResponseDecision:
    return to_reviewer_response_decision({"issue_number": issue_number, "response_state": "closed"})


def _untracked_decision(issue_number: int) -> ReviewerResponseDecision:
    return to_reviewer_response_decision(
        {"issue_number": issue_number, "response_state": "untracked", "reason": "no_review_entry"}
    )


def collect_issue314_state_health_input(
    bot,
    state: dict,
    request: Issue314StateHealthRepairRequest | None = None,
) -> Issue314StateHealthClassificationInput:
    request = request or _default_request(bot)
    _require_request_identity(request)
    rows = _active_rows(state)
    snapshots: dict[int, dict[str, object]] = {}
    reviewer_responses: dict[int, ReviewerResponseDecision] = {}
    projections: dict[int, StatusLabelProjectionResult] = {}
    scans: dict[int, ReminderCommentScan | None] = {}
    for row in rows:
        issue_number = int(row["issue_number"])
        review_data = row["review_data"]
        try:
            snapshot_result = bot.github.get_issue_or_pr_snapshot_result(issue_number)
        except (AssertionError, AttributeError, RuntimeError):
            snapshot_result = None
        snapshot = (
            snapshot_result.payload
            if snapshot_result is not None
            and snapshot_result.ok
            and isinstance(snapshot_result.payload, dict)
            else None
        )
        if snapshot is not None:
            snapshots[issue_number] = snapshot
        scans[issue_number] = _comment_scan(bot, issue_number)
        if not isinstance(review_data, dict):
            continue
        if snapshot is None:
            continue
        try:
            projection = reviews.project_status_label_projection_for_item(
                bot,
                issue_number,
                state,
                issue_snapshot=snapshot,
            )
        except RuntimeError:
            if isinstance(snapshot, dict) and str(snapshot.get("state", "")).lower() == "closed":
                reviewer_responses[issue_number] = _closed_decision(issue_number)
            elif review_data is None:
                reviewer_responses[issue_number] = _untracked_decision(issue_number)
            continue
        projections[issue_number] = projection
        decision_output = projection.projection_metadata.get("decision_output")
        if isinstance(decision_output, dict):
            reviewer_responses[issue_number] = to_reviewer_response_decision(decision_output)
        else:
            response_state = reviews.compute_reviewer_response_state(
                bot,
                issue_number,
                review_data,
                issue_snapshot=snapshot,
            )
            decision, _cadence, _scan = overdue._effective_response_with_cadence(
                bot,
                issue_number,
                review_data,
                dict(response_state),
            )
            reviewer_responses[issue_number] = decision
    return Issue314StateHealthClassificationInput(
        state_issue_number=request.state_issue_number,
        validation_nonce=request.validation_nonce,
        active_review_rows=rows,
        live_snapshots=snapshots,
        reviewer_responses=reviewer_responses,
        status_projections=projections,
        reminder_scans=scans,
        evaluated_repo=request.evaluated_repo,
        head_sha=request.head_sha,
        evaluated_ref=request.evaluated_ref,
        workflow_path=request.workflow_path,
        run_id=request.run_id,
        run_attempt=request.run_attempt,
    )


def _live_head_sha(snapshot: dict[str, object], projection: StatusLabelProjectionResult | None) -> str | None:
    pull_request = snapshot.get("pull_request")
    if isinstance(pull_request, dict):
        head = pull_request.get("head")
        if isinstance(head, dict) and isinstance(head.get("sha"), str):
            return head["sha"]
    if projection is not None:
        decision = projection.projection_metadata.get("decision_output")
        if isinstance(decision, dict) and isinstance(decision.get("current_head_sha"), str):
            return decision["current_head_sha"]
    return None


def _row_from_input(input: Issue314StateHealthClassificationInput, row: dict[str, object]) -> Issue314StateHealthRow:
    issue_number = int(row["issue_number"])
    review_data = row.get("review_data") if isinstance(row.get("review_data"), dict) else {}
    snapshot = input.live_snapshots.get(issue_number)
    projection = input.status_projections.get(issue_number)
    decision = input.reviewer_responses.get(issue_number)
    scan = input.reminder_scans.get(issue_number)
    blockers: list[str] = []
    if snapshot is None:
        blockers.append("live_snapshot_unavailable")
    if decision is None:
        blockers.append("reviewer_response_unavailable")
    if projection is None and (snapshot is None or str(snapshot.get("state", "")).lower() != "closed"):
        blockers.append("status_projection_unavailable")
    if scan is None:
        blockers.append("reminder_scan_unavailable")

    if blockers:
        health = "blocked"
        repair = "blocked"
        status_risk = "blocked_unknown"
        automated_risk = None
        reason = ",".join(sorted(blockers))
    else:
        assert snapshot is not None
        live_state = str(snapshot.get("state", "")).lower()
        if live_state == "closed":
            health = "closed_item_pending_removal"
            repair = "not_attempted"
            status_risk = "no_label_required"
            automated_risk = False
            reason = "closed_live_item_has_active_issue314_row"
        else:
            assert projection is not None
            delta = projection.delta
            has_drift = bool(delta.labels_to_add or delta.labels_to_remove)
            automated_risk = projection.response_state == "awaiting_reviewer_response"
            if automated_risk:
                health = "blocked"
                repair = "blocked"
                status_risk = "blocked_unknown"
                reason = "row_can_still_trigger_reviewer_reminder"
                blockers.append(reason)
            elif has_drift and issue_number == 264:
                health = "operator_action_required"
                repair = "not_attempted"
                status_risk = "operator_visible_stale"
                reason = "pr264_status_label_repair_deferred_to_issue_scoped_live_repair"
            elif has_drift:
                health = "repairable"
                repair = "not_attempted"
                status_risk = "repairable_drift"
                reason = "status_label_projection_drift"
            else:
                health = "healthy"
                repair = "not_attempted"
                status_risk = "aligned" if delta.desired_status_labels else "no_label_required"
                reason = "status_projection_aligned"

    live_status_labels = actual_status_labels_from_snapshot(snapshot or {})
    return Issue314StateHealthRow(
        issue_number=issue_number,
        current_reviewer=review_data.get("current_reviewer") if isinstance(review_data.get("current_reviewer"), str) else None,
        active_head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
        live_state=str(snapshot.get("state")) if snapshot is not None and snapshot.get("state") is not None else None,
        is_pull_request=bool(snapshot is not None and isinstance(snapshot.get("pull_request"), dict)),
        live_head_sha=_live_head_sha(snapshot or {}, projection),
        live_status_labels=live_status_labels,
        reviewer_response=decision.to_output() if decision is not None else {},
        status_projection=projection.to_output() if projection is not None else {},
        reminder_scan=scan.to_output() if scan is not None else None,
        health_classification=health,
        repair_outcome=repair,
        classification_reason=reason,
        status_label_risk=status_risk,
        automated_reminder_risk=automated_risk,
        blockers=tuple(blockers),
    )


def classify_issue314_state_health(input: Issue314StateHealthClassificationInput) -> Issue314StateHealthSummary:
    _require_identity(input.__dict__, reason="classification_input")
    inventory = tuple(_row_from_input(input, row) for row in input.active_review_rows)
    counts: dict[str, int] = {}
    for row in inventory:
        counts[row.health_classification] = counts.get(row.health_classification, 0) + 1
    rows_repairable = tuple(row.issue_number for row in inventory if row.health_classification == "repairable")
    rows_operator = tuple(row.issue_number for row in inventory if row.health_classification == "operator_action_required")
    rows_blocked = tuple(row.issue_number for row in inventory if row.health_classification == "blocked")
    status_projection_summary = {
        str(row.issue_number): {
            "response_state": row.status_projection.get("response_state"),
            "actual_status_labels": row.status_projection.get("delta", {}).get("actual_status_labels", [])
            if isinstance(row.status_projection.get("delta"), dict)
            else [],
            "desired_status_labels": row.status_projection.get("delta", {}).get("desired_status_labels", [])
            if isinstance(row.status_projection.get("delta"), dict)
            else [],
            "status_label_risk": row.status_label_risk,
        }
        for row in inventory
    }
    pr264 = next((row for row in inventory if row.issue_number == 264), None)
    pr264_no_ping_status = "pass"
    if pr264 is not None and pr264.automated_reminder_risk is not False:
        pr264_no_ping_status = "blocked"
    request = Issue314StateHealthRepairRequest(
        repair_action="preview-issue314-state-health",
        state_issue_number=input.state_issue_number,
        validation_nonce=input.validation_nonce,
        evaluated_repo=input.evaluated_repo,
        head_sha=input.head_sha,
        evaluated_ref=input.evaluated_ref,
        workflow_path=input.workflow_path,
        run_id=input.run_id,
        run_attempt=input.run_attempt,
    )
    artifact_name = _artifact_name("reviewer-bot-preview-output", request)
    return Issue314StateHealthSummary(
        schema_version=1,
        preview_action="preview-issue314-state-health",
        state_issue_number=input.state_issue_number,
        issue_number=input.state_issue_number,
        validation_nonce=input.validation_nonce,
        active_review_row_count=len(inventory),
        active_rows_inspected=tuple(row.issue_number for row in inventory),
        row_inventory=inventory,
        row_health_summary=counts,
        status_projection_summary=status_projection_summary,
        rows_repairable=rows_repairable,
        rows_operator_action_required=rows_operator,
        rows_blocked=rows_blocked,
        pr264_no_ping_status=pr264_no_ping_status,
        lock_attempted=False,
        state_save_attempted=False,
        tracked_state_mutations_attempted=False,
        touched_projection_attempted=False,
        evaluated_repo=input.evaluated_repo,
        head_sha=input.head_sha,
        evaluated_ref=input.evaluated_ref,
        workflow_path=input.workflow_path,
        run_id=input.run_id,
        run_attempt=input.run_attempt,
        artifact_name=artifact_name,
        artifact_file="preview-output.json",
        output_keys=(),
    )


def classify_issue314_state_health_rows(bot, state: dict) -> Issue314StateHealthSummary:
    return classify_issue314_state_health(collect_issue314_state_health_input(bot, state))


def run_issue314_state_health_repair(
    bot,
    state: dict,
    request: Issue314StateHealthRepairRequest,
) -> Issue314StateHealthRepairSummary:
    _require_request_identity(request)
    bot.assert_lock_held("run_issue314_state_health_repair")
    classification_input = collect_issue314_state_health_input(bot, state, request)
    summary = classify_issue314_state_health(classification_input)
    active_reviews = state.get("active_reviews") if isinstance(state, dict) else None
    rows_removed_closed: list[int] = []
    rows_repaired: list[int] = []
    status_labels_changed: list[int] = []
    rows_blocked = list(summary.rows_blocked)
    if isinstance(active_reviews, dict):
        for row in summary.row_inventory:
            if row.health_classification == "closed_item_pending_removal":
                active_reviews.pop(str(row.issue_number), None)
                rows_removed_closed.append(row.issue_number)
            elif row.health_classification == "repairable":
                projection = classification_input.status_projections.get(row.issue_number)
                if projection is None:
                    rows_blocked.append(row.issue_number)
                    continue
                sync_result = reviews.apply_status_label_delta(bot, row.issue_number, projection.delta)
                rows_repaired.append(row.issue_number)
                if sync_result.changed:
                    status_labels_changed.append(row.issue_number)
    elif summary.active_review_row_count:
        rows_blocked.extend(summary.active_rows_inspected)
    result = "blocked" if rows_blocked or summary.rows_repairable and not rows_repaired else "changed" if rows_removed_closed or rows_repaired else "already_healthy"
    return Issue314StateHealthRepairSummary(
        schema_version=1,
        repair_action=request.repair_action,
        state_issue_number=request.state_issue_number,
        issue_number=request.state_issue_number,
        validation_nonce=request.validation_nonce,
        target_collection_mode="global_issue314_state_health",
        active_rows_inspected=summary.active_rows_inspected,
        rows_repaired=tuple(rows_repaired),
        rows_removed_closed=tuple(rows_removed_closed),
        rows_operator_action_required=summary.rows_operator_action_required,
        rows_blocked=tuple(sorted(set(rows_blocked))),
        status_labels_changed=tuple(status_labels_changed),
        reviewer_facing_reminder_posts_attempted=0,
        manual_issue314_edit_status="not_attempted",
        state_store_mutation_mode="bot_owned_state_store" if rows_removed_closed else "not_required",
        evaluated_repo=request.evaluated_repo,
        head_sha=request.head_sha,
        evaluated_ref=request.evaluated_ref,
        workflow_path=request.workflow_path,
        run_id=request.run_id,
        run_attempt=request.run_attempt,
        artifact_name=_artifact_name("reviewer-bot-repair-output", request),
        artifact_file="issue314-state-health-repair-summary.json",
        output_keys=(),
        result=result,
    )


def emit_issue314_state_health_repair_summary(summary: Issue314StateHealthRepairSummary) -> None:
    path = os.environ.get("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", "").strip()
    if not path:
        raise RuntimeError("issue314_state_health_repair_summary_path_missing")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary.to_output(), indent=2) + "\n", encoding="utf-8")
