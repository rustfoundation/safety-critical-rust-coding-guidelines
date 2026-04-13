"""Review lifecycle and review-freshness helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote

from scripts.reviewer_bot_core import live_review_support

from . import review_state
from .config import (
    MANDATORY_TRIAGE_APPROVER_LABEL,
    MANDATORY_TRIAGE_ESCALATION_TEMPLATE,
    MANDATORY_TRIAGE_SATISFIED_TEMPLATE,
    STATUS_LABELS,
)
from .reviews_projection import (
    desired_labels_from_response_state,
)


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


parse_github_timestamp = live_review_support.parse_github_timestamp


def get_latest_review_by_reviewer(bot, reviews: list[dict], reviewer: str) -> dict | None:
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), "")
    for review in reviews:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        review_id = str(review.get("id", ""))
        review_key = (submitted_at, review_id)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review
    return latest_review


def get_latest_valid_current_reviewer_review_for_cycle(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    reviews: list[dict] | None = None,
) -> dict | None:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return None
    boundary = review_state.get_current_cycle_boundary(bot, review_data)
    if boundary is None:
        return None
    if reviews is None:
        reviews = bot.github.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), "")
    for review in reviews:
        if not isinstance(review, dict):
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != current_reviewer.lower():
            continue
        state = str(review.get("state", "")).upper()
        if state not in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}:
            continue
        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None or submitted_at < boundary:
            continue
        commit_id = review.get("commit_id")
        if not isinstance(commit_id, str) or not commit_id.strip():
            continue
        review_id = str(review.get("id", ""))
        review_key = (submitted_at, review_id)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review
    return latest_review


def resolve_pr_approval_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> tuple[dict | None, dict | None, str | None]:
    completion, write_approval = bot.rebuild_pr_approval_state(
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if completion is None or write_approval is None:
        return None, None, "live_review_state_unknown"
    return completion, write_approval, None


def apply_pr_approval_state(
    review_data: dict,
    *,
    completion: dict,
    write_approval: dict,
    current_head_sha: str,
) -> None:
    review_data["active_head_sha"] = current_head_sha
    review_data["current_cycle_completion"] = completion
    review_data["current_cycle_write_approval"] = write_approval
    if completion.get("completed"):
        review_data["review_completed_at"] = _now_iso()
        review_data["review_completed_by"] = None
        review_data["review_completion_source"] = "live_review_rebuild"
    else:
        review_data["review_completed_at"] = None
        review_data["review_completed_by"] = None
        review_data["review_completion_source"] = None


def is_triage_or_higher(bot, username: str) -> bool:
    status = live_review_support.permission_status(bot, username, "triage")
    if status == "unavailable":
        raise RuntimeError(f"Unable to determine triage permission for @{username}")
    return status == "granted"


def trigger_mandatory_approver_escalation(bot, state: dict, issue_number: int) -> bool:
    from scripts.reviewer_bot_core import mandatory_approver_policy

    review_data = review_state.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    decision = mandatory_approver_policy.decide_mandatory_approver_escalation(
        review_data,
        now=_now_iso(),
        label_exists=bot.github.ensure_label_exists(MANDATORY_TRIAGE_APPROVER_LABEL),
    )
    state_changed = False
    if decision["require_escalation"]:
        review_data["mandatory_approver_required"] = True
        review_data["mandatory_approver_satisfied_by"] = None
        review_data["mandatory_approver_satisfied_at"] = None
        state_changed = True
    if decision["attempt_label_apply"]:
        try:
            if bot.add_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL):
                if decision["record_label_applied_at"]:
                    review_data["mandatory_approver_label_applied_at"] = str(decision["now"])
                    state_changed = True
        except RuntimeError as exc:
            _log(bot, "warning", f"Unable to apply escalation label on #{issue_number}: {exc}", issue_number=issue_number, error=str(exc))
    if decision["post_ping"]:
        if bot.github.post_comment(issue_number, MANDATORY_TRIAGE_ESCALATION_TEMPLATE):
            review_data["mandatory_approver_pinged_at"] = str(decision["now"])
            state_changed = True
    return state_changed


def satisfy_mandatory_approver_requirement(bot, state: dict, issue_number: int, approver: str) -> bool:
    from scripts.reviewer_bot_core import mandatory_approver_policy

    review_data = review_state.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    decision = mandatory_approver_policy.decide_mandatory_approver_satisfaction(
        review_data,
        approver=approver,
        now=_now_iso(),
    )
    if not decision["allow"]:
        return False
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_satisfied_by"] = str(decision["approver"])
    review_data["mandatory_approver_satisfied_at"] = str(decision["now"])
    try:
        bot.remove_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL)
    except RuntimeError as exc:
        _log(bot, "warning", f"Unable to remove escalation label on #{issue_number}: {exc}", issue_number=issue_number, error=str(exc))
    bot.github.post_comment(issue_number, MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver=approver))
    return True


def get_pull_request_reviews(bot, issue_number: int) -> list[dict] | None:
    result = live_review_support.read_pull_request_reviews_result(bot, issue_number)
    if not result.get("ok"):
        return None
    reviews = result.get("reviews")
    return reviews if isinstance(reviews, list) else None


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
def rebuild_pr_approval_state_result(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    from scripts.reviewer_bot_core import approval_policy

    result = approval_policy.compute_pr_approval_state_result(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if not result.get("ok"):
        return result
    apply_pr_approval_state(
        review_data,
        completion=result["completion"],
        write_approval=result["write_approval"],
        current_head_sha=str(result["current_head_sha"]),
    )
    return {
        "ok": True,
        "completion": result["completion"],
        "write_approval": result["write_approval"],
    }


def rebuild_pr_approval_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> tuple[dict | None, dict | None]:
    result = rebuild_pr_approval_state_result(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if not result.get("ok"):
        return None, None
    return result.get("completion"), result.get("write_approval")


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


def compute_reviewer_response_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    issue_snapshot: dict | None = None,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    from scripts.reviewer_bot_core import reviewer_response_policy

    return reviewer_response_policy.compute_reviewer_response_state(
        bot,
        issue_number,
        review_data,
        issue_snapshot=issue_snapshot,
        pull_request=pull_request,
        reviews=reviews,
    )


def project_status_labels_for_item(
    bot,
    issue_number: int,
    state: dict,
    *,
    issue_snapshot: dict | None = None,
) -> tuple[set[str] | None, dict[str, str | None]]:
    if issue_snapshot is None:
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return None, {"state": "projection_failed", "reason": "issue_snapshot_unavailable"}
    if str(issue_snapshot.get("state", "")).lower() == "closed":
        return set(), {"state": "closed", "reason": None}

    review_data = review_state.ensure_review_entry(state, issue_number)
    if review_data is None:
        return set(), {"state": "untracked", "reason": "no_review_entry"}
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return set(), {"state": "untracked", "reason": "no_current_reviewer"}

    response_state = compute_reviewer_response_state(bot, issue_number, review_data, issue_snapshot=issue_snapshot)
    state_name = response_state.get("state")
    reason = response_state.get("reason")
    return desired_labels_from_response_state(str(state_name), None if reason is None else str(reason))


def sync_status_labels(bot, issue_number: int, desired_labels: set[str], actual_labels: Iterable[str]) -> bool:
    actual_status_labels = {label for label in actual_labels if label in STATUS_LABELS}
    to_add = desired_labels - actual_status_labels
    to_remove = actual_status_labels - desired_labels
    if not to_add and not to_remove:
        return False
    for label in STATUS_LABELS:
        if not bot.github.ensure_label_exists(label):
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
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
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
            response = bot.github_api_request(
                "GET",
                f"issues?state=open&labels={encoded_label}&per_page=100&page={page}",
                retry_policy="idempotent_read",
            )
            if not response.ok:
                raise RuntimeError(
                    f"Failed to list open items for status label '{label}': {response.failure_kind or 'unavailable'}"
                )
            result = response.payload
            if not isinstance(result, list):
                raise RuntimeError(
                    f"Failed to list open items for status label '{label}': invalid_payload"
                )
            for item in result:
                if isinstance(item, dict):
                    number = item.get("number")
                    if isinstance(number, int):
                        numbers.add(number)
            if len(result) < 100:
                break
            page += 1
    return sorted(numbers)


def list_open_tracked_review_items(state: dict) -> list[int]:
    numbers: set[int] = set()
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return []
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        current_reviewer = review_data.get("current_reviewer")
        if not isinstance(current_reviewer, str) or not current_reviewer.strip():
            continue
        try:
            issue_number = int(issue_key)
        except (TypeError, ValueError):
            continue
        if issue_number > 0:
            numbers.add(issue_number)
    return sorted(numbers)
