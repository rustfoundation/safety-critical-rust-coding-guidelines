"""Review lifecycle and review-freshness helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

from .config import (
    MANDATORY_TRIAGE_APPROVER_LABEL,
    MANDATORY_TRIAGE_ESCALATION_TEMPLATE,
    MANDATORY_TRIAGE_SATISFIED_TEMPLATE,
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
    STATUS_LABELS,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_github_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _ensure_channel_map(review_entry: dict, name: str) -> dict:
    value = review_entry.get(name)
    if not isinstance(value, dict):
        value = {"accepted": None, "seen_keys": []}
        review_entry[name] = value
    if not isinstance(value.get("seen_keys"), list):
        value["seen_keys"] = []
    return value


def _ensure_dict(review_entry: dict, name: str) -> dict:
    value = review_entry.get(name)
    if not isinstance(value, dict):
        value = {}
        review_entry[name] = value
    return value


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    issue_key = str(issue_number)
    if "active_reviews" not in state or not isinstance(state.get("active_reviews"), dict):
        state["active_reviews"] = {}
    review_entry = state["active_reviews"].get(issue_key)
    if review_entry is None:
        if not create:
            return None
        review_entry = {}
        state["active_reviews"][issue_key] = review_entry
    elif isinstance(review_entry, list):
        review_entry = {"skipped": review_entry}
        state["active_reviews"][issue_key] = review_entry
    if not isinstance(review_entry, dict):
        return None

    defaults: dict[str, Any] = {
        "skipped": [],
        "current_reviewer": None,
        "cycle_started_at": None,
        "active_cycle_started_at": None,
        "assigned_at": None,
        "active_head_sha": None,
        "last_reviewer_activity": None,
        "transition_warning_sent": None,
        "assignment_method": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "mandatory_approver_required": False,
        "mandatory_approver_label_applied_at": None,
        "mandatory_approver_pinged_at": None,
        "mandatory_approver_satisfied_by": None,
        "mandatory_approver_satisfied_at": None,
        "repair_needed": None,
        "overdue_anchor": None,
    }
    for field, default in defaults.items():
        if field not in review_entry:
            review_entry[field] = default
    if not isinstance(review_entry.get("skipped"), list):
        review_entry["skipped"] = []

    for channel in (
        "reviewer_comment",
        "reviewer_review",
        "contributor_comment",
        "contributor_revision",
        "review_dismissal",
    ):
        _ensure_channel_map(review_entry, channel)
    for mapping in (
        "deferred_gaps",
        "observer_discovery_watermarks",
        "pending_privileged_commands",
        "current_cycle_completion",
        "current_cycle_write_approval",
    ):
        _ensure_dict(review_entry, mapping)
    reconciled_source_events = review_entry.get("reconciled_source_events")
    if not isinstance(reconciled_source_events, list):
        review_entry["reconciled_source_events"] = []
    return review_entry


def _reset_cycle_state(review_data: dict) -> None:
    for channel in (
        "reviewer_comment",
        "reviewer_review",
        "contributor_comment",
        "contributor_revision",
        "review_dismissal",
    ):
        review_data[channel] = {"accepted": None, "seen_keys": []}
    review_data["current_cycle_completion"] = {}
    review_data["current_cycle_write_approval"] = {}
    review_data["overdue_anchor"] = None
    if isinstance(review_data.get("pending_privileged_commands"), dict):
        review_data["pending_privileged_commands"] = {}


def set_current_reviewer(
    state: dict,
    issue_number: int,
    reviewer: str,
    assignment_method: str = "round-robin",
) -> None:
    now = _now_iso()
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return
    review_data["current_reviewer"] = reviewer
    review_data["cycle_started_at"] = now
    review_data["active_cycle_started_at"] = now
    review_data["assigned_at"] = now
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None
    review_data["assignment_method"] = assignment_method
    review_data["review_completed_at"] = None
    review_data["review_completed_by"] = None
    review_data["review_completion_source"] = None
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_label_applied_at"] = None
    review_data["mandatory_approver_pinged_at"] = None
    review_data["mandatory_approver_satisfied_by"] = None
    review_data["mandatory_approver_satisfied_at"] = None
    review_data["active_head_sha"] = None
    _reset_cycle_state(review_data)


def _semantic_key_seen(review_data: dict, channel_name: str, semantic_key: str) -> bool:
    channel = _ensure_channel_map(review_data, channel_name)
    return semantic_key in channel["seen_keys"]


def _compare_records(left: dict | None, right: dict | None) -> int:
    if right is None:
        return 1
    if left is None:
        return -1
    left_time = parse_github_timestamp(left.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    right_time = parse_github_timestamp(right.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    left_rank = int(left.get("source_precedence", 0))
    right_rank = int(right.get("source_precedence", 0))
    left_key = str(left.get("semantic_key", ""))
    right_key = str(right.get("semantic_key", ""))
    left_tuple = (left_time, left_rank, left_key)
    right_tuple = (right_time, right_rank, right_key)
    if left_tuple > right_tuple:
        return 1
    if left_tuple < right_tuple:
        return -1
    return 0


def accept_channel_event(
    review_data: dict,
    channel_name: str,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str | None = None,
    reviewed_head_sha: str | None = None,
    source_precedence: int = 0,
    payload: dict | None = None,
    dismissal_only: bool = False,
) -> bool:
    channel = _ensure_channel_map(review_data, channel_name)
    if semantic_key in channel["seen_keys"]:
        return False
    channel["seen_keys"].append(semantic_key)
    if dismissal_only:
        channel["accepted"] = channel.get("accepted") or {
            "semantic_key": semantic_key,
            "timestamp": timestamp,
        }
        return True
    candidate = {
        "semantic_key": semantic_key,
        "timestamp": timestamp,
        "actor": actor,
        "reviewed_head_sha": reviewed_head_sha,
        "source_precedence": source_precedence,
        "payload": payload or {},
    }
    current = channel.get("accepted")
    if _compare_records(candidate, current) >= 0:
        channel["accepted"] = candidate
    return True


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or current_reviewer.lower() != reviewer.lower():
        return False
    review_data["last_reviewer_activity"] = _now_iso()
    review_data["transition_warning_sent"] = None
    return True


def mark_review_complete(state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    now = _now_iso()
    review_data["review_completed_at"] = now
    review_data["review_completed_by"] = reviewer or None
    review_data["review_completion_source"] = source
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None
    review_data["current_cycle_completion"] = {
        "completed": True,
        "completed_at": now,
        "source": source,
        "reviewer": reviewer,
    }
    return True


def is_triage_or_higher(bot, username: str) -> bool:
    return bot.check_user_permission(username, "triage")


def trigger_mandatory_approver_escalation(bot, state: dict, issue_number: int) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    now = _now_iso()
    state_changed = False
    if not review_data.get("mandatory_approver_required"):
        review_data["mandatory_approver_required"] = True
        review_data["mandatory_approver_satisfied_by"] = None
        review_data["mandatory_approver_satisfied_at"] = None
        state_changed = True
    if bot.ensure_label_exists(MANDATORY_TRIAGE_APPROVER_LABEL):
        try:
            if bot.add_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL):
                if review_data.get("mandatory_approver_label_applied_at") is None:
                    review_data["mandatory_approver_label_applied_at"] = now
                    state_changed = True
        except RuntimeError as exc:
            print(f"WARNING: Unable to apply escalation label on #{issue_number}: {exc}", file=bot.sys.stderr)
    if review_data.get("mandatory_approver_pinged_at") is None:
        if bot.post_comment(issue_number, MANDATORY_TRIAGE_ESCALATION_TEMPLATE):
            review_data["mandatory_approver_pinged_at"] = now
            state_changed = True
    return state_changed


def satisfy_mandatory_approver_requirement(bot, state: dict, issue_number: int, approver: str) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None or not review_data.get("mandatory_approver_required"):
        return False
    if review_data.get("mandatory_approver_satisfied_at"):
        return False
    now = _now_iso()
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_satisfied_by"] = approver
    review_data["mandatory_approver_satisfied_at"] = now
    try:
        bot.remove_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL)
    except RuntimeError as exc:
        print(f"WARNING: Unable to remove escalation label on #{issue_number}: {exc}", file=bot.sys.stderr)
    bot.post_comment(issue_number, MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver=approver))
    return True


def get_pull_request_reviews(bot, issue_number: int) -> list[dict] | None:
    reviews: list[dict] = []
    page = 1
    while True:
        result = bot.github_api("GET", f"pulls/{issue_number}/reviews?per_page=100&page={page}")
        if result is None:
            return None
        if not isinstance(result, list):
            return reviews
        page_reviews = [review for review in result if isinstance(review, dict)]
        reviews.extend(page_reviews)
        if len(result) < 100:
            return reviews
        page += 1


def collapse_latest_reviews_by_login(reviews: list[dict]) -> dict[str, dict]:
    latest_by_login: dict[str, tuple[datetime, str, dict]] = {}
    for review in reviews:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        review_id = str(review.get("id", ""))
        key = author.lower()
        review_key = (submitted_at, review_id)
        current = latest_by_login.get(key)
        if current is None or review_key >= (current[0], current[1]):
            latest_by_login[key] = (submitted_at, review_id, review)
    return {login: item[2] for login, item in latest_by_login.items()}


def get_current_cycle_boundary(bot, review_data: dict) -> datetime | None:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        boundary = bot.parse_iso8601_timestamp(review_data.get(field))
        if boundary is not None:
            return boundary
    return None


def rebuild_pr_approval_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> tuple[dict | None, dict | None]:
    boundary = get_current_cycle_boundary(bot, review_data)
    if boundary is None:
        return None, None
    if pull_request is None:
        pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        return None, None
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return None, None
    if reviews is None:
        reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None, None

    survivors: dict[str, dict] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        state = str(review.get("state", "")).upper()
        if state == "DISMISSED":
            continue
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None or submitted_at < boundary:
            continue
        commit_id = review.get("commit_id")
        if not isinstance(commit_id, str) or not commit_id.strip():
            continue
        if commit_id.strip() != current_head:
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        review_id = str(review.get("id", ""))
        key = author.lower()
        candidate_key = (submitted_at, review_id)
        current = survivors.get(key)
        if current is None:
            survivors[key] = review
            continue
        current_key = (
            parse_github_timestamp(current.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(current.get("id", "")),
        )
        if candidate_key >= current_key:
            survivors[key] = review

    approvals = [review for review in survivors.values() if str(review.get("state", "")).upper() == "APPROVED"]
    completion = {
        "completed": bool(approvals),
        "current_head_sha": current_head,
        "qualifying_review_ids": [review.get("id") for review in approvals],
    }

    permission_cache: dict[str, bool] = {}
    has_write_approval = False
    write_approvers: list[str] = []
    for review in approvals:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.check_user_permission(author, "push")
        if permission_cache[cache_key]:
            has_write_approval = True
            write_approvers.append(author)
    write_approval = {
        "has_write_approval": has_write_approval,
        "write_approvers": write_approvers,
        "current_head_sha": current_head,
    }

    review_data["active_head_sha"] = current_head
    review_data["current_cycle_completion"] = completion
    review_data["current_cycle_write_approval"] = write_approval
    if completion["completed"]:
        review_data["review_completed_at"] = _now_iso()
        review_data["review_completed_by"] = None
        review_data["review_completion_source"] = "live_review_rebuild"
    else:
        review_data["review_completed_at"] = None
        review_data["review_completed_by"] = None
        review_data["review_completion_source"] = None
    return completion, write_approval


def pr_has_current_write_approval(
    bot,
    issue_number: int,
    review_data: dict,
    permission_cache: dict[str, bool] | None = None,
    reviews: list[dict] | None = None,
) -> bool | None:
    del permission_cache
    completion, write_approval = rebuild_pr_approval_state(bot, issue_number, review_data, reviews=reviews)
    if completion is None or write_approval is None:
        return None
    return bool(write_approval.get("has_write_approval"))


def _record_timestamp(record: dict | None) -> datetime | None:
    if not isinstance(record, dict):
        return None
    return parse_github_timestamp(record.get("timestamp"))


def _compare_cross_channel_conversation(contributor: dict | None, reviewer: dict | None) -> int:
    contributor_time = _record_timestamp(contributor) or datetime.min.replace(tzinfo=timezone.utc)
    reviewer_time = _record_timestamp(reviewer) or datetime.min.replace(tzinfo=timezone.utc)
    contributor_key = str((contributor or {}).get("semantic_key", ""))
    reviewer_key = str((reviewer or {}).get("semantic_key", ""))
    if (contributor_time, contributor_key) == (reviewer_time, reviewer_key):
        return 0
    if contributor_time > reviewer_time:
        return 1
    if contributor_time < reviewer_time:
        return -1
    if contributor_key >= reviewer_key:
        return 1
    return -1


def project_status_labels_for_item(
    bot,
    issue_number: int,
    state: dict,
    *,
    issue_snapshot: dict | None = None,
) -> tuple[set[str] | None, dict[str, str | None]]:
    if issue_snapshot is None:
        issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return None, {"state": "projection_failed", "reason": "issue_snapshot_unavailable"}
    is_pr = isinstance(issue_snapshot.get("pull_request"), dict)
    if str(issue_snapshot.get("state", "")).lower() == "closed":
        return set(), {"state": "closed", "reason": None}

    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return set(), {"state": "untracked", "reason": "no_review_entry"}
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return set(), {"state": "untracked", "reason": "no_current_reviewer"}

    reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    contributor_comment = review_data.get("contributor_comment", {}).get("accepted")

    if not reviewer_comment and not reviewer_review:
        return ({STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}, {"state": "awaiting_reviewer_response", "reason": "no_reviewer_activity"})

    if is_pr:
        pull_request = bot.github_api("GET", f"pulls/{issue_number}")
        if not isinstance(pull_request, dict):
            return None, {"state": "projection_failed", "reason": "pull_request_unavailable"}
        head = pull_request.get("head")
        current_head = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(current_head, str) or not current_head.strip():
            return None, {"state": "projection_failed", "reason": "pull_request_head_unavailable"}
        review_data["active_head_sha"] = current_head
        latest_review_head = None
        if isinstance(reviewer_review, dict):
            latest_review_head = reviewer_review.get("reviewed_head_sha")
        if not isinstance(latest_review_head, str) or latest_review_head != current_head:
            return ({STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}, {"state": "awaiting_reviewer_response", "reason": "review_head_stale"})

    if _compare_cross_channel_conversation(contributor_comment, reviewer_comment) > 0:
        return ({STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}, {"state": "awaiting_reviewer_response", "reason": "contributor_comment_newer"})

    if is_pr:
        completion, write_approval = rebuild_pr_approval_state(bot, issue_number, review_data)
        if completion is None or write_approval is None:
            return None, {"state": "projection_failed", "reason": "live_review_state_unknown"}
        if not completion.get("completed"):
            return ({STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}, {"state": "awaiting_contributor_response", "reason": "completion_missing"})
        if not write_approval.get("has_write_approval"):
            return ({STATUS_AWAITING_WRITE_APPROVAL_LABEL}, {"state": "awaiting_write_approval", "reason": "write_approval_missing"})
        return set(), {"state": "done", "reason": "write_approval_present"}

    completion = review_data.get("current_cycle_completion")
    if not isinstance(completion, dict) or not completion.get("completed"):
        if review_data.get("review_completed_at"):
            return set(), {"state": "done", "reason": None}
        return ({STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}, {"state": "awaiting_contributor_response", "reason": "completion_missing"})
    return set(), {"state": "done", "reason": None}


def sync_status_labels(bot, issue_number: int, desired_labels: set[str], actual_labels: Iterable[str]) -> bool:
    actual_status_labels = {label for label in actual_labels if label in STATUS_LABELS}
    to_add = desired_labels - actual_status_labels
    to_remove = actual_status_labels - desired_labels
    if not to_add and not to_remove:
        return False
    for label in STATUS_LABELS:
        if not bot.ensure_label_exists(label):
            raise RuntimeError(f"Unable to ensure reviewer-bot status label exists: {label}")
    changed = False
    for label in sorted(to_remove):
        if not bot.remove_label_with_status(issue_number, label):
            raise RuntimeError(f"Unable to remove reviewer-bot status label '{label}' from #{issue_number}")
        changed = True
    for label in sorted(to_add):
        if not bot.add_label_with_status(issue_number, label):
            raise RuntimeError(f"Unable to add reviewer-bot status label '{label}' to #{issue_number}")
        changed = True
    return changed


def sync_status_labels_for_items(bot, state: dict, issue_numbers: Iterable[int]) -> bool:
    changed = False
    for issue_number in sorted({n for n in issue_numbers if isinstance(n, int) and n > 0}):
        issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
        desired_labels, metadata = bot.project_status_labels_for_item(issue_number, state, issue_snapshot=issue_snapshot)
        if desired_labels is None:
            reason = metadata.get("reason") if isinstance(metadata, dict) else "unknown"
            raise RuntimeError(f"Failed to derive reviewer-bot status labels for #{issue_number}: {reason}")
        if not isinstance(issue_snapshot, dict):
            raise RuntimeError(f"Failed to refresh issue/PR snapshot for #{issue_number}")
        labels = issue_snapshot.get("labels", [])
        actual_labels = set()
        if isinstance(labels, list):
            for label in labels:
                if isinstance(label, dict):
                    name = label.get("name")
                    if isinstance(name, str):
                        actual_labels.add(name)
        if bot.sync_status_labels(issue_number, desired_labels, actual_labels):
            changed = True
    return changed


def list_open_items_with_status_labels(bot) -> list[int]:
    numbers: set[int] = set()
    for label in sorted(STATUS_LABELS):
        page = 1
        encoded_label = quote(label, safe="")
        while True:
            result = bot.github_api("GET", f"issues?state=open&labels={encoded_label}&per_page=100&page={page}")
            if result is None:
                raise RuntimeError(f"Failed to list open items for status label '{label}'")
            if not isinstance(result, list):
                break
            for item in result:
                if isinstance(item, dict):
                    number = item.get("number")
                    if isinstance(number, int):
                        numbers.add(number)
            if len(result) < 100:
                break
            page += 1
    return sorted(numbers)


def handle_pr_approved_review(bot, state: dict, issue_number: int, review_author: str, completion_source: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    current_reviewer = review_data.get("current_reviewer")
    author_is_designated = isinstance(current_reviewer, str) and current_reviewer.lower() == review_author.lower()
    author_is_triage = is_triage_or_higher(bot, review_author)
    state_changed = False
    if author_is_designated:
        if mark_review_complete(state, issue_number, review_author, completion_source):
            state_changed = True
        if author_is_triage:
            if satisfy_mandatory_approver_requirement(bot, state, issue_number, review_author):
                state_changed = True
            return state_changed
        if trigger_mandatory_approver_escalation(bot, state, issue_number):
            state_changed = True
        return state_changed
    if review_data.get("mandatory_approver_required") and author_is_triage:
        if satisfy_mandatory_approver_requirement(bot, state, issue_number, review_author):
            state_changed = True
    return state_changed
