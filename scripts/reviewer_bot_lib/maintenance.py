"""Manual maintenance and operator-dispatch handlers for reviewer-bot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import (
    issue314_state_health,
    maintenance_privileged,
    maintenance_schedule,
    overdue,
    reviews,
)
from .event_inputs import build_manual_dispatch_request
from .project_board import (
    preview_board_projection_for_item,
    reviewer_board_preflight,
)
from .reviews_projection import status_label_projection_output

ScheduleHandlerResult = maintenance_schedule.ScheduleHandlerResult
SCHEDULE_LIKE_MANUAL_ACTIONS = frozenset({"check-overdue"})
_PENDING_ISSUE314_REPAIR_SUMMARY_ATTR = "_reviewer_bot_pending_issue314_state_health_repair_summary"
_now_iso = maintenance_privileged._now_iso
_finalize_schedule_result = maintenance_schedule._finalize_schedule_result
_record_maintenance_repair_marker = maintenance_schedule._record_maintenance_repair_marker
_run_tracked_pr_maintenance = maintenance_schedule._run_tracked_pr_maintenance
repair_missing_reviewer_review_state = maintenance_schedule.repair_missing_reviewer_review_state
maybe_record_head_observation_repair = maintenance_schedule.maybe_record_head_observation_repair
check_overdue_reviews = maintenance_schedule.check_overdue_reviews
handle_overdue_review_warning = maintenance_schedule.handle_overdue_review_warning
backfill_transition_notice_if_present = maintenance_schedule.backfill_transition_notice_if_present
handle_transition_notice = maintenance_schedule.handle_transition_notice
sweep_deferred_gaps = maintenance_schedule.sweep_deferred_gaps


def status_projection_repair_needed(bot, state: dict) -> bool:
    current_epoch = state.get("status_projection_epoch")
    return current_epoch != bot.STATUS_PROJECTION_EPOCH


def collect_status_projection_repair_items(bot, state: dict) -> list[int]:
    return maintenance_schedule.collect_status_projection_repair_items(bot, state)


@dataclass(frozen=True)
class ManualDispatchProjectionPolicy:
    action: str
    issue_number: int | None
    allow_epoch_repair_expansion: bool
    allow_status_label_sync: bool
    reason: str

    def to_output(self) -> dict[str, object]:
        return {
            "action": self.action,
            "issue_number": self.issue_number,
            "allow_epoch_repair_expansion": self.allow_epoch_repair_expansion,
            "allow_status_label_sync": self.allow_status_label_sync,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StatusLabelRepairRequest:
    action: str
    issue_number: int | None
    validation_nonce: str
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str

    def to_output(self) -> dict[str, object]:
        return {
            "action": self.action,
            "issue_number": self.issue_number,
            "validation_nonce": self.validation_nonce,
            "evaluated_repo": self.evaluated_repo,
            "head_sha": self.head_sha,
            "evaluated_ref": self.evaluated_ref,
            "workflow_path": self.workflow_path,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
        }


@dataclass(frozen=True)
class StatusLabelRepairItemResult:
    issue_number: int
    before_status_labels: tuple[str, ...]
    desired_status_labels: tuple[str, ...]
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    result: str

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "before_status_labels": sorted(self.before_status_labels),
            "desired_status_labels": sorted(self.desired_status_labels),
            "labels_added": sorted(self.labels_added),
            "labels_removed": sorted(self.labels_removed),
            "result": self.result,
        }


@dataclass(frozen=True)
class StatusLabelRepairSummary:
    schema_version: int
    repair_action: str
    issue_number: int | None
    issue_numbers: tuple[int, ...]
    validation_nonce: str
    evaluated_repo: str
    head_sha: str
    evaluated_ref: str
    workflow_path: str
    run_id: str
    run_attempt: str
    artifact_name: str
    artifact_file: str
    output_keys: tuple[str, ...]
    status_projection_epoch: str | None
    before: tuple[StatusLabelRepairItemResult, ...]
    after: tuple[StatusLabelRepairItemResult, ...]
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    state_save_attempted: bool
    tracked_state_mutations_attempted: bool
    touched_projection_attempted: bool
    target_collection_mode: str
    result: str

    def to_output(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "repair_action": self.repair_action,
            "issue_number": self.issue_number,
            "issue_numbers": sorted(self.issue_numbers),
            "validation_nonce": self.validation_nonce,
            "evaluated_repo": self.evaluated_repo,
            "head_sha": self.head_sha,
            "evaluated_ref": self.evaluated_ref,
            "workflow_path": self.workflow_path,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_name": self.artifact_name,
            "artifact_file": self.artifact_file,
            "output_keys": [],
            "status_projection_epoch": self.status_projection_epoch,
            "before": [item.to_output() for item in sorted(self.before, key=lambda item: item.issue_number)],
            "after": [item.to_output() for item in sorted(self.after, key=lambda item: item.issue_number)],
            "labels_added": sorted(self.labels_added),
            "labels_removed": sorted(self.labels_removed),
            "state_save_attempted": self.state_save_attempted,
            "tracked_state_mutations_attempted": self.tracked_state_mutations_attempted,
            "touched_projection_attempted": self.touched_projection_attempted,
            "target_collection_mode": self.target_collection_mode,
            "result": self.result,
        }
        payload["output_keys"] = sorted(payload.keys())
        return payload


def _config(bot, name: str, default: str = "") -> str:
    return bot.get_config_value(name, default).strip()


def _run_id(bot) -> str:
    return _config(bot, "GITHUB_RUN_ID") or _config(bot, "WORKFLOW_RUN_ID")


def _run_attempt(bot) -> str:
    return _config(bot, "GITHUB_RUN_ATTEMPT") or "1"


def _evaluated_repo(bot) -> str:
    return _config(bot, "EVALUATED_REPO") or _config(bot, "GITHUB_REPOSITORY")


def _head_sha(bot) -> str:
    return _config(bot, "HEAD_SHA") or _config(bot, "GITHUB_SHA")


def _evaluated_ref(bot) -> str:
    return _config(bot, "EVALUATED_REF") or _head_sha(bot)


def _artifact_name(prefix: str, bot) -> str:
    return f"{prefix}-{_run_id(bot)}-attempt-{_run_attempt(bot)}"


def _preview_identity(bot) -> dict[str, str]:
    run_id = _run_id(bot)
    run_attempt = _run_attempt(bot)
    return {
        "evaluated_repo": _evaluated_repo(bot),
        "head_sha": _head_sha(bot),
        "evaluated_ref": _evaluated_ref(bot),
        "workflow_path": ".github/workflows/reviewer-bot-preview.yml",
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact_name": f"reviewer-bot-preview-output-{run_id}-attempt-{run_attempt}",
        "artifact_file": "preview-output.json",
    }


def _repair_artifact_fields(request: StatusLabelRepairRequest) -> dict[str, str]:
    return {
        "artifact_name": f"reviewer-bot-repair-output-{request.run_id}-attempt-{request.run_attempt}",
        "artifact_file": "repair-summary.json",
    }


def _issue314_request(bot, request) -> issue314_state_health.Issue314StateHealthRepairRequest:
    state_issue_number = bot.state_issue_number()
    return issue314_state_health.Issue314StateHealthRepairRequest(
        repair_action=request.action,
        state_issue_number=state_issue_number,
        validation_nonce=request.validation_nonce,
        evaluated_repo=_evaluated_repo(bot),
        head_sha=_head_sha(bot),
        evaluated_ref=_evaluated_ref(bot),
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml" if request.action.startswith("repair-") else ".github/workflows/reviewer-bot-preview.yml",
        run_id=_run_id(bot),
        run_attempt=_run_attempt(bot),
    )


def emit_pending_issue314_state_health_repair_summary(bot) -> None:
    summary = getattr(bot, _PENDING_ISSUE314_REPAIR_SUMMARY_ATTR, None)
    if summary is None:
        return
    issue314_state_health.emit_issue314_state_health_repair_summary(summary)
    setattr(bot, _PENDING_ISSUE314_REPAIR_SUMMARY_ATTR, None)


def derive_manual_dispatch_projection_policy(request) -> ManualDispatchProjectionPolicy:
    action = request.action or ""
    issue_number = request.issue_number if isinstance(request.issue_number, int) else None
    if action == "repair-review-status-labels" and issue_number is not None and issue_number > 0:
        return ManualDispatchProjectionPolicy(action, issue_number, False, True, "targeted_status_label_repair")
    if action == "repair-review-status-labels":
        return ManualDispatchProjectionPolicy(action, issue_number, True, True, "broad_status_label_repair")
    if action in {"preview-check-overdue", "preview-status-label-projection", "preview-issue314-state-health"}:
        return ManualDispatchProjectionPolicy(action, issue_number, False, False, "read_only_preview")
    return ManualDispatchProjectionPolicy(action, issue_number, True, True, "normal_manual_mutation")


def build_status_label_repair_request(bot, request) -> StatusLabelRepairRequest:
    if request.action != "repair-review-status-labels":
        raise RuntimeError("status_label_repair_request_blocked:unsupported_action")
    validation_nonce = request.validation_nonce.strip()
    evaluated_repo = _evaluated_repo(bot)
    head_sha = _head_sha(bot)
    evaluated_ref = _evaluated_ref(bot)
    run_id = _run_id(bot)
    run_attempt = _run_attempt(bot)
    workflow_path = ".github/workflows/reviewer-bot-sweeper-repair.yml"
    missing = []
    for name, value in {
        "validation_nonce": validation_nonce,
        "evaluated_repo": evaluated_repo,
        "head_sha": head_sha,
        "evaluated_ref": evaluated_ref,
        "workflow_path": workflow_path,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }.items():
        if not value:
            missing.append(name)
    if missing:
        raise RuntimeError("status_label_repair_request_blocked:" + ",".join(sorted(missing)))
    return StatusLabelRepairRequest(
        action=request.action,
        issue_number=request.issue_number,
        validation_nonce=validation_nonce,
        evaluated_repo=evaluated_repo,
        head_sha=head_sha,
        evaluated_ref=evaluated_ref,
        workflow_path=workflow_path,
        run_id=run_id,
        run_attempt=run_attempt,
    )


def collect_status_label_repair_targets(bot, state: dict, request: StatusLabelRepairRequest) -> tuple[int, ...]:
    del state
    if isinstance(request.issue_number, int) and request.issue_number > 0:
        return (request.issue_number,)
    return tuple(reviews.list_open_items_with_status_labels(bot))


def run_status_label_repair(bot, state: dict, request: StatusLabelRepairRequest) -> StatusLabelRepairSummary:
    targets = collect_status_label_repair_targets(bot, state, request)
    before: list[StatusLabelRepairItemResult] = []
    after: list[StatusLabelRepairItemResult] = []
    labels_added: set[str] = set()
    labels_removed: set[str] = set()
    for issue_number in targets:
        projection = reviews.project_status_label_projection_for_item(bot, issue_number, state)
        delta = projection.delta
        sync_result = reviews.apply_status_label_delta(bot, issue_number, delta)
        item_result = "changed" if sync_result.changed else "already_aligned"
        before.append(
            StatusLabelRepairItemResult(
                issue_number=issue_number,
                before_status_labels=delta.actual_status_labels,
                desired_status_labels=delta.desired_status_labels,
                labels_added=delta.labels_to_add,
                labels_removed=delta.labels_to_remove,
                result=item_result,
            )
        )
        after.append(
            StatusLabelRepairItemResult(
                issue_number=issue_number,
                before_status_labels=delta.desired_status_labels,
                desired_status_labels=delta.desired_status_labels,
                labels_added=sync_result.labels_added,
                labels_removed=sync_result.labels_removed,
                result=item_result,
            )
        )
        labels_added.update(sync_result.labels_added)
        labels_removed.update(sync_result.labels_removed)
    result = "changed" if labels_added or labels_removed else "already_aligned"
    artifact = _repair_artifact_fields(request)
    payload = StatusLabelRepairSummary(
        schema_version=1,
        repair_action=request.action,
        issue_number=request.issue_number,
        issue_numbers=targets,
        validation_nonce=request.validation_nonce,
        evaluated_repo=request.evaluated_repo,
        head_sha=request.head_sha,
        evaluated_ref=request.evaluated_ref,
        workflow_path=request.workflow_path,
        run_id=request.run_id,
        run_attempt=request.run_attempt,
        artifact_name=artifact["artifact_name"],
        artifact_file=artifact["artifact_file"],
        output_keys=(),
        status_projection_epoch=state.get("status_projection_epoch") if isinstance(state.get("status_projection_epoch"), str) else None,
        before=tuple(before),
        after=tuple(after),
        labels_added=tuple(sorted(labels_added)),
        labels_removed=tuple(sorted(labels_removed)),
        state_save_attempted=False,
        tracked_state_mutations_attempted=False,
        touched_projection_attempted=False,
        target_collection_mode="issue_scoped" if isinstance(request.issue_number, int) and request.issue_number > 0 else "broad",
        result=result,
    )
    output_keys = tuple(payload.to_output()["output_keys"])
    return StatusLabelRepairSummary(**{**payload.__dict__, "output_keys": output_keys})


def emit_status_label_repair_summary(summary: StatusLabelRepairSummary) -> None:
    path = os.environ.get("REPAIR_SUMMARY_PATH", "").strip()
    if not path:
        raise RuntimeError("repair_summary_path_missing")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary.to_output(), indent=2) + "\n", encoding="utf-8")


def _preview_output_base(bot, state: dict, request) -> dict[str, object]:
    if request.issue_number is None or request.issue_number <= 0:
        raise RuntimeError("Preview actions require ISSUE_NUMBER to be set to a positive integer")
    identity = _preview_identity(bot)
    return {
        "schema_version": 1,
        "preview_action": request.action,
        "issue_number": request.issue_number,
        "validation_nonce": request.validation_nonce,
        "evaluated_repo": identity["evaluated_repo"],
        "head_sha": identity["head_sha"],
        "evaluated_ref": identity["evaluated_ref"],
        "workflow_path": identity["workflow_path"],
        "run_id": identity["run_id"],
        "run_attempt": identity["run_attempt"],
        "artifact_name": identity["artifact_name"],
        "artifact_file": identity["artifact_file"],
        "output_keys": [],
        **overdue.evaluate_overdue_review_preview(bot, state, request.issue_number),
        "lock_attempted": False,
        "state_save_attempted": False,
        "tracked_state_mutations_attempted": False,
        "touched_projection_attempted": False,
    }


def _emit_preview_json(payload: dict[str, object]) -> None:
    payload["output_keys"] = sorted(payload.keys())
    print(json.dumps(payload, indent=2, sort_keys=False))


def is_schedule_like_manual_action(action: str | None) -> bool:
    return action in SCHEDULE_LIKE_MANUAL_ACTIONS


def handle_manual_dispatch(bot, state: dict) -> bool:
    request = build_manual_dispatch_request(bot)
    if is_schedule_like_manual_action(request.action):
        raise RuntimeError("schedule-like manual action must use handle_manual_dispatch_result")
    return _handle_manual_dispatch_request(bot, state, request)


def handle_scheduled_check_result(bot, state: dict) -> ScheduleHandlerResult:
    return maintenance_schedule.handle_scheduled_check_result(bot, state)


def handle_manual_dispatch_result(bot, state: dict) -> ScheduleHandlerResult:
    request = build_manual_dispatch_request(bot)
    if is_schedule_like_manual_action(request.action):
        return handle_scheduled_check_result(bot, state)
    state_changed = _handle_manual_dispatch_request(bot, state, request)
    return maintenance_schedule._finalize_schedule_result(bot, state_changed)


def _handle_manual_dispatch_request(bot, state: dict, request) -> bool:
    action = request.action
    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False
    if action == "preview-check-overdue":
        _emit_preview_json(_preview_output_base(bot, state, request))
        return False
    if action == "preview-status-label-projection":
        if request.issue_number is None or request.issue_number <= 0:
            raise RuntimeError("Preview actions require ISSUE_NUMBER to be set to a positive integer")
        projection = reviews.project_status_label_projection_for_item(bot, request.issue_number, state)
        payload = status_label_projection_output(
            projection,
            preview_action=request.action,
            validation_nonce=request.validation_nonce,
            **_preview_identity(bot),
        )
        payload["lock_attempted"] = False
        payload["state_save_attempted"] = False
        payload["tracked_state_mutations_attempted"] = False
        payload["touched_projection_attempted"] = False
        _emit_preview_json(payload)
        return False
    if action == "preview-issue314-state-health":
        summary = issue314_state_health.classify_issue314_state_health(
            issue314_state_health.collect_issue314_state_health_input(
                bot,
                state,
                _issue314_request(bot, request),
            )
        )
        _emit_preview_json(summary.to_output())
        return False
    if action == "preview-reviewer-board":
        preflight = reviewer_board_preflight(bot)
        if not preflight.enabled:
            print("Reviewer board preview skipped: reviewer board is disabled.")
            return False
        if not preflight.valid:
            raise RuntimeError(
                "Reviewer board preview preflight failed: " + "; ".join(preflight.errors)
            )

        payload = _preview_output_base(bot, state, request)
        preview = preview_board_projection_for_item(bot, state, request.issue_number)
        desired = preview.desired
        payload["board_attention"] = desired.needs_attention if desired is not None else None
        payload["board_waiting_since"] = desired.waiting_since if desired is not None else None
        _emit_preview_json(payload)
        return False
    bot.assert_lock_held("handle_manual_dispatch")
    if action == "sync-members":
        _, changes = bot.adapters.workflow.sync_members_with_queue(state)
        return bool(changes)
    if action == "repair-review-status-labels":
        repair_request = build_status_label_repair_request(bot, request)
        summary = run_status_label_repair(bot, state, repair_request)
        emit_status_label_repair_summary(summary)
        return False
    if action == "repair-issue314-state-health":
        summary = issue314_state_health.run_issue314_state_health_repair(
            bot,
            state,
            _issue314_request(bot, request),
        )
        setattr(bot, _PENDING_ISSUE314_REPAIR_SUMMARY_ATTR, summary)
        return bool(summary.rows_removed_closed)
    if action == "execute-pending-privileged-command":
        source_event_key = request.privileged_source_event_key
        if not source_event_key:
            raise RuntimeError("Missing PRIVILEGED_SOURCE_EVENT_KEY for privileged command execution")
        return maintenance_privileged.execute_pending_privileged_command(bot, state, source_event_key)
    return False
