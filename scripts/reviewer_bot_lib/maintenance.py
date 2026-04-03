"""Maintenance and operator-dispatch handlers for reviewer-bot."""

from __future__ import annotations

import yaml

from .context import PrivilegedCommandRequest
from .event_inputs import build_manual_dispatch_request
from .lifecycle import maybe_record_head_observation_repair
from .overdue import (
    backfill_transition_notice_if_present,
    check_overdue_reviews,
    handle_overdue_review_warning,
)
from .project_board import (
    format_preview_for_output,
    preview_board_projection_for_item,
    reviewer_board_preflight,
)
from .review_state import (
    list_open_tracked_review_items,
    repair_missing_reviewer_review_state,
)
from .sweeper import sweep_deferred_gaps


def _now_iso(bot) -> str:
    return bot.datetime.now(bot.timezone.utc).isoformat()


def build_revalidated_privileged_command_request(
    bot,
    *,
    issue_number: int,
    actor: str,
    command_name: str,
    labels: set[str],
) -> PrivilegedCommandRequest:
    workflow_run_reconcile_pr_number = bot.get_config_value("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "").strip()
    return PrivilegedCommandRequest(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
        is_pull_request=False,
        issue_labels=tuple(sorted(labels)),
        target_repo_root=bot.get_config_value("REVIEWER_BOT_TARGET_REPO_ROOT", "").strip(),
        workflow_run_reconcile_pr_number=int(workflow_run_reconcile_pr_number) if workflow_run_reconcile_pr_number else None,
        workflow_run_reconcile_head_sha=bot.get_config_value("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "").strip(),
        workflow_run_head_sha=bot.get_config_value("WORKFLOW_RUN_HEAD_SHA", "").strip(),
    )


def _clear_maintenance_repair_marker(review_data: dict, phase: str) -> bool:
    marker = review_data.get("repair_needed")
    if not isinstance(marker, dict):
        return False
    if marker.get("kind") != "live_read_failure":
        return False
    if marker.get("phase") != phase:
        return False
    review_data["repair_needed"] = None
    return True


def _repair_marker_matches(existing: dict | None, candidate: dict) -> bool:
    if not isinstance(existing, dict):
        return False
    return {
        key: value for key, value in existing.items() if key != "recorded_at"
    } == {
        key: value for key, value in candidate.items() if key != "recorded_at"
    }


def _record_maintenance_repair_marker(
    bot,
    review_data: dict,
    *,
    phase: str,
    reason: str,
    failure_kind: str | None,
) -> bool:
    marker = {
        "kind": "live_read_failure",
        "phase": phase,
        "reason": reason,
        "failure_kind": failure_kind,
        "recorded_at": _now_iso(bot),
    }
    existing_marker = review_data.get("repair_needed")
    if _repair_marker_matches(existing_marker, marker):
        return False
    review_data["repair_needed"] = marker
    return True


def status_projection_repair_needed(bot, state: dict) -> bool:
    current_epoch = state.get("status_projection_epoch")
    return current_epoch != bot.STATUS_PROJECTION_EPOCH


def collect_status_projection_repair_items(bot, state: dict) -> list[int]:
    numbers = set(bot.list_open_items_with_status_labels())
    numbers.update(list_open_tracked_review_items(state))
    return sorted(number for number in numbers if isinstance(number, int) and number > 0)


def handle_manual_dispatch(bot, state: dict) -> bool:
    request = build_manual_dispatch_request(bot)
    action = request.action
    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
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

        issue_numbers: list[int] = []
        if request.issue_number:
            issue_numbers = [request.issue_number]
        else:
            active_reviews = state.get("active_reviews")
            if isinstance(active_reviews, dict):
                candidates: set[int] = set()
                for issue_key, review_data in active_reviews.items():
                    if not isinstance(review_data, dict):
                        continue
                    try:
                        issue_number = int(issue_key)
                    except (TypeError, ValueError):
                        continue
                    if issue_number > 0:
                        candidates.add(issue_number)
                issue_numbers = sorted(candidates)

        previews = [preview_board_projection_for_item(bot, state, issue_number) for issue_number in issue_numbers]
        print(
            yaml.safe_dump(
                format_preview_for_output(preflight, previews),
                default_flow_style=False,
                sort_keys=False,
            ).rstrip()
        )
        return False
    bot.assert_lock_held("handle_manual_dispatch")
    if action == "sync-members":
        _, changes = bot.sync_members_with_queue(state)
        return bool(changes)
    if action == "repair-review-status-labels":
        for issue_number in bot.list_open_items_with_status_labels():
            bot.collect_touched_item(issue_number)
        return False
    if action == "check-overdue":
        return bot.handle_scheduled_check(state)
    if action == "execute-pending-privileged-command":
        source_event_key = request.privileged_source_event_key
        if not source_event_key:
            raise RuntimeError("Missing PRIVILEGED_SOURCE_EVENT_KEY for privileged command execution")
        for issue_key, review_data in (state.get("active_reviews") or {}).items():
            if not isinstance(review_data, dict):
                continue
            pending = review_data.get("pending_privileged_commands")
            if not isinstance(pending, dict) or source_event_key not in pending:
                continue
            record = pending[source_event_key]
            if not isinstance(record, dict):
                raise RuntimeError("Pending privileged command record is malformed")
            if record.get("status") != "pending":
                return False
            issue_number = int(record.get("issue_number") or int(issue_key))
            actor = str(record.get("actor", "")).strip()
            command_name = record.get("command_name")
            if command_name != "accept-no-fls-changes":
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "unsupported_command"
                return True
            issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
            if not isinstance(issue_snapshot, dict) or isinstance(issue_snapshot.get("pull_request"), dict):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "live_target_invalid"
                return True
            labels: set[str] = set()
            for label in issue_snapshot.get("labels", []):
                if not isinstance(label, dict):
                    continue
                name = label.get("name")
                if isinstance(name, str):
                    labels.add(name)
            permission_status = bot.get_user_permission_status(actor, "triage")
            if bot.FLS_AUDIT_LABEL not in labels:
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "live_revalidation_failed"
                return True
            if permission_status == "unavailable":
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "live_permission_unavailable"
                return True
            if permission_status != "granted":
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "live_revalidation_failed"
                return True
            request = build_revalidated_privileged_command_request(
                bot,
                issue_number=issue_number,
                actor=actor,
                command_name=str(command_name),
                labels=labels,
            )
            message, success = bot.handle_accept_no_fls_changes_command(issue_number, actor, request=request)
            record["completed_at"] = _now_iso(bot)
            record["result_message"] = message
            record["status"] = "executed" if success else "failed_closed"
            return True
        raise RuntimeError(f"Pending privileged command not found for {source_event_key}")
    return False


def handle_scheduled_check(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_scheduled_check")
    changed = sweep_deferred_gaps(bot, state)
    active_reviews = state.get("active_reviews")
    if isinstance(active_reviews, dict):
        for issue_key, review_data in active_reviews.items():
            if not isinstance(review_data, dict) or not review_data.get("current_reviewer"):
                continue
            issue_number = int(issue_key)
            issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
            if not isinstance(issue_snapshot, dict) or not isinstance(issue_snapshot.get("pull_request"), dict):
                continue
            try:
                if repair_missing_reviewer_review_state(bot, issue_number, review_data):
                    changed = True
                    bot.collect_touched_item(issue_number)
                if _clear_maintenance_repair_marker(review_data, "review_repair"):
                    changed = True
            except Exception as exc:
                print(
                    f"WARNING: Scheduled repair failed for #{issue_number} during review_repair: {exc}",
                    file=bot.sys.stderr,
                )
                if _record_maintenance_repair_marker(
                    bot,
                    review_data,
                    phase="review_repair",
                    reason=str(exc),
                    failure_kind=None,
                ):
                    changed = True
                continue

            try:
                repair_result = maybe_record_head_observation_repair(bot, issue_number, review_data)
            except Exception as exc:
                print(
                    f"WARNING: Scheduled repair failed for #{issue_number} during head_observation_repair: {exc}",
                    file=bot.sys.stderr,
                )
                if _record_maintenance_repair_marker(
                    bot,
                    review_data,
                    phase="head_observation_repair",
                    reason=str(exc),
                    failure_kind=None,
                ):
                    changed = True
                continue

            if repair_result.changed:
                changed = True
                bot.collect_touched_item(issue_number)
            if repair_result.outcome in {"skipped_unavailable", "skipped_not_found", "invalid_live_payload"}:
                if _record_maintenance_repair_marker(
                    bot,
                    review_data,
                    phase="head_observation_repair",
                    reason=repair_result.reason or repair_result.outcome,
                    failure_kind=repair_result.failure_kind,
                ):
                    changed = True
            elif _clear_maintenance_repair_marker(review_data, "head_observation_repair"):
                changed = True
    overdue_reviews = check_overdue_reviews(bot, state)
    if not overdue_reviews:
        return changed
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        if review["needs_warning"]:
            if handle_overdue_review_warning(bot, state, issue_number, reviewer):
                changed = True
        elif review["needs_transition"]:
            if backfill_transition_notice_if_present(bot, state, issue_number):
                changed = True
            elif bot.handle_transition_notice(state, issue_number, reviewer):
                changed = True
    return changed
