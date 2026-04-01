"""Issue and PR lifecycle handlers for reviewer-bot."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from .guidance import get_fls_audit_guidance, get_issue_guidance, get_pr_guidance


@dataclass(frozen=True)
class HeadObservationRepairResult:
    changed: bool
    outcome: str
    failure_kind: str | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.changed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def _is_pr_event() -> bool:
    return os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"


def _normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def handle_transition_notice(bot, state: dict, issue_number: int, reviewer: str) -> bool:
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    if review_data.get("transition_notice_sent_at"):
        return False
    notice_message = f"""🔔 **Transition Period Ended**

@{reviewer}, the {bot.TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

You may still continue this review, or use `{bot.BOT_MENTION} /pass`, `{bot.BOT_MENTION} /release`, or `{bot.BOT_MENTION} /away` if you need to step back.

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    if not bot.post_comment(issue_number, notice_message):
        return False
    bot.reviews_module.record_transition_notice_sent(
        review_data,
        bot.datetime.now(bot.timezone.utc).isoformat(),
    )
    return True


def handle_issue_or_pr_opened(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_or_pr_opened")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    if tracked_reviewer:
        return False
    current_assignees = bot.get_issue_assignees(issue_number)
    if current_assignees is None:
        raise RuntimeError(f"Unable to determine assignees for #{issue_number}")
    if current_assignees:
        return False
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        labels = []
    if not any(label in bot.REVIEW_LABELS for label in labels):
        return False
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    reviewer = bot.get_next_reviewer(state, skip_usernames={issue_author} if issue_author else set())
    if not reviewer:
        bot.post_comment(issue_number, f"⚠️ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue.")
        return False
    is_pr = _is_pr_event()
    assignment_attempt = bot.request_reviewer_assignment(issue_number, reviewer)
    bot.set_current_reviewer(state, issue_number, reviewer)
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if is_pr and isinstance(review_data, dict):
        head_sha = os.environ.get("PR_HEAD_SHA", "").strip()
        if head_sha:
            review_data["active_head_sha"] = head_sha
    bot.record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")
    failure_comment = bot.get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        bot.post_comment(issue_number, failure_comment)
    if is_pr and assignment_attempt.success:
        bot.post_comment(issue_number, get_pr_guidance(reviewer, issue_author))
    if not is_pr:
        guidance = get_fls_audit_guidance(reviewer, issue_author) if bot.FLS_AUDIT_LABEL in labels else get_issue_guidance(reviewer, issue_author)
        bot.post_comment(issue_number, guidance)
    return True


def handle_issue_edited_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_edited_event")
    if _is_pr_event():
        return False
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_author = os.environ.get("ISSUE_AUTHOR", "").strip()
    editor = os.environ.get("SENDER_LOGIN", "").strip() or issue_author
    if not issue_author or editor.lower() != issue_author.lower():
        return False
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    updated_at = os.environ.get("ISSUE_UPDATED_AT", "").strip() or _now_iso()
    current_title = os.environ.get("ISSUE_TITLE", "")
    current_body = os.environ.get("ISSUE_BODY", "")
    previous_title = os.environ.get("ISSUE_CHANGES_TITLE_FROM", "")
    previous_body = os.environ.get("ISSUE_CHANGES_BODY_FROM", "")
    title_changed = _normalize_comment_body(current_title) != _normalize_comment_body(previous_title)
    body_changed = _normalize_comment_body(current_body) != _normalize_comment_body(previous_body)
    if not title_changed and not body_changed:
        return False
    if title_changed and body_changed:
        semantic_key = f"issues_edit_title_body:{issue_number}:{_semantic_digest(current_title)}:{_semantic_digest(current_body)}"
    elif title_changed:
        semantic_key = f"issues_edit_title:{issue_number}:{_semantic_digest(current_title)}"
    else:
        semantic_key = f"issues_edit_body:{issue_number}:{_semantic_digest(current_body)}"
    return bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_comment",
        semantic_key=semantic_key,
        timestamp=updated_at,
        actor=issue_author,
        source_precedence=0,
    )


def handle_labeled_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_labeled_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    label_name = os.environ.get("LABEL_NAME", "")
    is_pr = _is_pr_event()
    bot.collect_touched_item(issue_number)
    if label_name == "sign-off: create pr":
        if is_pr:
            return False
        review_data = bot.ensure_review_entry(state, issue_number)
        reviewer = review_data.get("current_reviewer") if review_data else None
        return bot.mark_review_complete(state, issue_number, reviewer, "issue_label: sign-off: create pr")
    if label_name not in bot.REVIEW_LABELS:
        return False
    return handle_issue_or_pr_opened(bot, state)


def handle_pull_request_target_synchronize(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_pull_request_target_synchronize")
    if _runtime_epoch(state) != "freshness_v15":
        print("V18 synchronize repair safe-noop before epoch flip")
        return False
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None or not review_data.get("current_reviewer"):
        return False
    head_sha = os.environ.get("PR_HEAD_SHA", "").strip()
    if not head_sha:
        raise RuntimeError("Missing PR_HEAD_SHA for synchronize event")
    bot.collect_touched_item(issue_number)
    previous_head_sha = review_data.get("active_head_sha")
    previous_completion = deepcopy(review_data.get("current_cycle_completion"))
    previous_write_approval = deepcopy(review_data.get("current_cycle_write_approval"))
    previous_review_completed_at = review_data.get("review_completed_at")
    previous_review_completed_by = review_data.get("review_completed_by")
    previous_review_completion_source = review_data.get("review_completion_source")
    review_data["active_head_sha"] = head_sha
    timestamp = os.environ.get("EVENT_CREATED_AT", "") or _now_iso()
    changed = bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=f"pull_request_sync:{issue_number}:{head_sha}",
        timestamp=timestamp,
        reviewed_head_sha=head_sha,
        source_precedence=1,
    )
    bot.reviews_module.rebuild_pr_approval_state(bot, issue_number, review_data)
    approval_changed = (
        previous_completion != review_data.get("current_cycle_completion")
        or previous_write_approval != review_data.get("current_cycle_write_approval")
        or previous_review_completed_at != review_data.get("review_completed_at")
        or previous_review_completed_by != review_data.get("review_completed_by")
        or previous_review_completion_source != review_data.get("review_completion_source")
    )
    return changed or previous_head_sha != review_data.get("active_head_sha") or approval_changed


def maybe_record_head_observation_repair(bot, issue_number: int, review_data: dict) -> HeadObservationRepairResult:
    try:
        response = bot.github_api_request("GET", f"pulls/{issue_number}", retry_policy="idempotent_read")
    except SystemExit:
        payload = bot.github_api("GET", f"pulls/{issue_number}")
        if not isinstance(payload, dict):
            return HeadObservationRepairResult(
                changed=False,
                outcome="skipped_unavailable",
                failure_kind="unavailable",
                reason="pull_request_unavailable",
            )
        response = bot.GitHubApiResult(
            status_code=200,
            payload=payload,
            headers={},
            text="",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        )
    if not response.ok:
        if response.failure_kind == "not_found":
            return HeadObservationRepairResult(
                changed=False,
                outcome="skipped_not_found",
                failure_kind=response.failure_kind,
                reason=f"pull_request_{response.failure_kind}",
            )
        return HeadObservationRepairResult(
            changed=False,
            outcome="skipped_unavailable",
            failure_kind=response.failure_kind,
            reason="pull_request_unavailable",
        )
    pull_request = response.payload
    if not isinstance(pull_request, dict):
        return HeadObservationRepairResult(
            changed=False,
            outcome="invalid_live_payload",
            failure_kind="invalid_payload",
            reason="pull_request_payload_invalid",
        )
    if str(pull_request.get("state", "")).lower() != "open":
        return HeadObservationRepairResult(changed=False, outcome="skipped_not_open")
    head = pull_request.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(head_sha, str) or not head_sha.strip():
        return HeadObservationRepairResult(
            changed=False,
            outcome="invalid_live_payload",
            failure_kind="invalid_payload",
            reason="pull_request_head_unavailable",
        )
    head_sha = head_sha.strip()
    current_head = review_data.get("active_head_sha")
    if current_head == head_sha:
        return HeadObservationRepairResult(changed=False, outcome="unchanged")
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    if isinstance(contributor_revision, dict) and contributor_revision.get("reviewed_head_sha") == head_sha:
        review_data["active_head_sha"] = head_sha
        return HeadObservationRepairResult(changed=True, outcome="changed")
    changed = bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=f"pull_request_head_observed:{issue_number}:{head_sha}",
        timestamp=_now_iso(),
        reviewed_head_sha=head_sha,
        source_precedence=0,
    )
    review_data["active_head_sha"] = head_sha
    review_data["current_cycle_completion"] = {}
    review_data["current_cycle_write_approval"] = {}
    review_data["review_completed_at"] = None
    review_data["review_completed_by"] = None
    review_data["review_completion_source"] = None
    return HeadObservationRepairResult(changed=changed, outcome="changed" if changed else "unchanged")


def handle_closed_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_closed_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        return True
    return False
