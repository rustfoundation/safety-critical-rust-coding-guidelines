"""Reviewer-bot event, deferred-evidence, and freshness handlers."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import yaml

from .lifecycle import maybe_record_head_observation_repair
from .sweeper import sweep_deferred_gaps


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def _is_pr_event() -> bool:
    return os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"


def _require_v18_for_pr(state: dict, context: str) -> bool:
    if not _is_pr_event():
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        print(f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True


def _require_legacy_for_legacy_pr(state: dict, context: str) -> bool:
    if not _is_pr_event():
        return True
    epoch = _runtime_epoch(state)
    if epoch == "freshness_v15":
        print(f"Legacy PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True



def get_latest_review_by_reviewer(bot, reviews: list[dict], reviewer: str) -> dict | None:
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), "")
    for review in reviews:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        review_id = str(review.get("id", ""))
        review_key = (submitted_at, review_id)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review
    return latest_review


def find_triage_approval_after(bot, reviews: list[dict], since: datetime | None) -> tuple[str, datetime] | None:
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[datetime, str, str]] = []
    for review in reviews:
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at
    return None


def handle_pull_request_review_event(bot, state: dict) -> bool:
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    if _runtime_epoch(state) == "freshness_v15":
        print("Legacy direct pull_request_review mutation disabled after epoch flip")
        return False
    review_action = os.environ.get("EVENT_ACTION", "").strip().lower()
    if review_action not in {"submitted", "dismissed"}:
        return False
    print(f"Deferring pull_request_review {review_action} for #{issue_number}")
    return False


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
                record["completed_at"] = _now_iso()
                record["result"] = "unsupported_command"
                return True
            issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
            if not isinstance(issue_snapshot, dict) or isinstance(issue_snapshot.get("pull_request"), dict):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso()
                record["result"] = "live_target_invalid"
                return True
            labels = {
                label.get("name")
                for label in issue_snapshot.get("labels", [])
                if isinstance(label, dict) and isinstance(label.get("name"), str)
            }
            if bot.FLS_AUDIT_LABEL not in labels or not bot.check_user_permission(actor, "triage"):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso()
                record["result"] = "live_revalidation_failed"
                return True
            message, success = bot.handle_accept_no_fls_changes_command(issue_number, actor)
            record["completed_at"] = _now_iso()
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
    overdue_reviews = bot.check_overdue_reviews(state)
    if not overdue_reviews:
        return changed
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        if review["needs_warning"]:
            if bot.handle_overdue_review_warning(state, issue_number, reviewer):
                changed = True
        elif review["needs_transition"]:
            bot.handle_transition_notice(state, issue_number, reviewer)
            changed = True
    return changed
