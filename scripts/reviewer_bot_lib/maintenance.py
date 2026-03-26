"""Maintenance and operator-dispatch handlers for reviewer-bot."""

from __future__ import annotations

import json
import os

import yaml

from .lifecycle import maybe_record_head_observation_repair
from .overdue import (
    backfill_transition_notice_if_present,
    check_overdue_reviews,
    handle_overdue_review_warning,
)
from .sweeper import sweep_deferred_gaps


def _now_iso(bot) -> str:
    return bot.datetime.now(bot.timezone.utc).isoformat()


def handle_manual_dispatch(bot, state: dict) -> bool:
    action = os.environ.get("MANUAL_ACTION", "")
    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
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
        source_event_key = os.environ.get("PRIVILEGED_SOURCE_EVENT_KEY", "").strip()
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
            if bot.FLS_AUDIT_LABEL not in labels or not bot.check_user_permission(actor, "triage"):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso(bot)
                record["result"] = "live_revalidation_failed"
                return True
            os.environ["ISSUE_LABELS"] = json.dumps(sorted(labels))
            message, success = bot.handle_accept_no_fls_changes_command(issue_number, actor)
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
            if maybe_record_head_observation_repair(bot, issue_number, review_data):
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
