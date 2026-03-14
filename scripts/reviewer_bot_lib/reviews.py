"""Review lifecycle and status projection helpers."""

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote

from .config import (
    MANDATORY_TRIAGE_APPROVER_LABEL,
    MANDATORY_TRIAGE_ESCALATION_TEMPLATE,
    MANDATORY_TRIAGE_SATISFIED_TEMPLATE,
    STATUS_AWAITING_REVIEW_COMPLETION_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
    STATUS_LABELS,
)


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    issue_key = str(issue_number)
    if "active_reviews" not in state:
        state["active_reviews"] = {}
    review_entry = state["active_reviews"].get(issue_key)
    if review_entry is None:
        if not create:
            return None
        review_entry = {
            "skipped": [],
            "current_reviewer": None,
            "cycle_started_at": None,
            "assigned_at": None,
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
        }
        state["active_reviews"][issue_key] = review_entry
    elif isinstance(review_entry, list):
        review_entry = {
            "skipped": review_entry,
            "current_reviewer": None,
            "cycle_started_at": None,
            "assigned_at": None,
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
        }
        state["active_reviews"][issue_key] = review_entry
    if not isinstance(review_entry, dict):
        return None
    if not isinstance(review_entry.get("skipped"), list):
        review_entry["skipped"] = []
    required_fields = {
        "current_reviewer": None,
        "cycle_started_at": None,
        "assigned_at": None,
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
    }
    for field, default in required_fields.items():
        if field not in review_entry:
            review_entry[field] = default
    return review_entry


def set_current_reviewer(state: dict, issue_number: int, reviewer: str, assignment_method: str = "round-robin") -> None:
    now = datetime.now(timezone.utc).isoformat()
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return
    review_data["current_reviewer"] = reviewer
    review_data["cycle_started_at"] = now
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


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None or review_data.get("review_completed_at"):
        return False
    current_reviewer = review_data.get("current_reviewer")
    if not current_reviewer or current_reviewer.lower() != reviewer.lower():
        return False
    now = datetime.now(timezone.utc).isoformat()
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None
    print(f"Updated reviewer activity for #{issue_number} by @{reviewer}")
    return True


def mark_review_complete(state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None or review_data.get("review_completed_at"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    review_data["review_completed_at"] = now
    review_data["review_completed_by"] = reviewer or None
    review_data["review_completion_source"] = source
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None
    reviewer_text = f" by @{reviewer}" if reviewer else ""
    print(f"Marked review complete for #{issue_number}{reviewer_text} ({source})")
    return True


def is_triage_or_higher(bot, username: str) -> bool:
    return bot.check_user_permission(username, "triage")


def trigger_mandatory_approver_escalation(bot, state: dict, issue_number: int) -> bool:
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    state_changed = False
    if not review_data.get("mandatory_approver_required"):
        review_data["mandatory_approver_required"] = True
        review_data["mandatory_approver_satisfied_by"] = None
        review_data["mandatory_approver_satisfied_at"] = None
        state_changed = True
    label_ensure_ok = bot.ensure_label_exists(MANDATORY_TRIAGE_APPROVER_LABEL)
    if label_ensure_ok:
        try:
            if bot.add_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL):
                if review_data.get("mandatory_approver_label_applied_at") is None:
                    review_data["mandatory_approver_label_applied_at"] = now
                    state_changed = True
        except RuntimeError as exc:
            print(f"WARNING: Unable to apply escalation label on #{issue_number}: {exc}", file=bot.sys.stderr)
    else:
        print(
            "WARNING: Escalation label ensure/create failed; proceeding with comment-only escalation",
            file=bot.sys.stderr,
        )
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
    now = datetime.now(timezone.utc).isoformat()
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_satisfied_by"] = approver
    review_data["mandatory_approver_satisfied_at"] = now
    try:
        bot.remove_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL)
    except RuntimeError as exc:
        print(f"WARNING: Unable to remove escalation label on #{issue_number}: {exc}", file=bot.sys.stderr)
    bot.post_comment(issue_number, MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver=approver))
    return True


def handle_pr_approved_review(bot, state: dict, issue_number: int, review_author: str, completion_source: str) -> bool:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        print(f"No active review entry for #{issue_number}")
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
    print(
        f"Ignoring approved review from @{review_author} on #{issue_number}; designated reviewer is @{current_reviewer}"
    )
    return state_changed


def parse_github_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
    latest_by_login: dict[str, tuple[datetime, int, dict]] = {}
    for index, review in enumerate(reviews):
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        key = author.lower()
        review_key = (submitted_at, index)
        current = latest_by_login.get(key)
        if current is None or review_key >= (current[0], current[1]):
            latest_by_login[key] = (submitted_at, index, review)
    return {login: item[2] for login, item in latest_by_login.items()}


def get_current_cycle_boundary(bot, review_data: dict) -> datetime | None:
    for field in ("cycle_started_at", "assigned_at", "review_completed_at"):
        boundary = bot.parse_iso8601_timestamp(review_data.get(field))
        if boundary is not None:
            return boundary
    return None


def pr_has_current_write_approval(bot, issue_number: int, review_data: dict, permission_cache: dict[str, bool] | None = None, reviews: list[dict] | None = None) -> bool | None:
    boundary = get_current_cycle_boundary(bot, review_data)
    if boundary is None:
        return False
    if reviews is None:
        reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None
    permission_cache = permission_cache if permission_cache is not None else {}
    latest_reviews = collapse_latest_reviews_by_login(reviews)
    for login, review in latest_reviews.items():
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None or submitted_at < boundary:
            continue
        if str(review.get("state", "")).upper() != "APPROVED":
            continue
        if login not in permission_cache:
            author = review.get("user", {}).get("login")
            if not isinstance(author, str) or not author.strip():
                return None
            permission_cache[login] = bot.check_user_permission(author, "push")
        if permission_cache[login]:
            return True
    return False


def project_status_labels_for_item(bot, issue_number: int, state: dict, *, issue_snapshot: dict | None = None) -> tuple[set[str] | None, dict[str, str | None]]:
    if issue_snapshot is None:
        issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return None, {"state": "projection_failed", "reason": "issue_snapshot_unavailable"}
    is_pr = isinstance(issue_snapshot.get("pull_request"), dict)
    state_name = str(issue_snapshot.get("state", "")).lower()
    if state_name == "closed":
        return set(), {"state": "closed", "reason": None}
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return set(), {"state": "untracked", "reason": "no_review_entry"}
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return set(), {"state": "untracked", "reason": "no_current_reviewer"}
    if not review_data.get("review_completed_at"):
        return ({STATUS_AWAITING_REVIEW_COMPLETION_LABEL}, {"state": "awaiting_review_completion", "reason": None})
    if not is_pr:
        return set(), {"state": "done", "reason": None}
    permission_cache: dict[str, bool] = {}
    has_write_approval = bot.pr_has_current_write_approval(issue_number, review_data, permission_cache=permission_cache)
    if has_write_approval is None:
        return None, {"state": "projection_failed", "reason": "write_approval_unknown"}
    if has_write_approval:
        return set(), {"state": "done", "reason": "write_approval_present"}
    return ({STATUS_AWAITING_WRITE_APPROVAL_LABEL}, {"state": "awaiting_write_approval", "reason": "write_approval_missing"})


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
        print(
            f"Status label projection for #{issue_number}: state={metadata.get('state')} desired={sorted(desired_labels)} actual={sorted(actual_labels & STATUS_LABELS)}"
        )
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
