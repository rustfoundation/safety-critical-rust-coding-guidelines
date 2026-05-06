"""Issue and PR lifecycle handlers for reviewer-bot."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from . import assignment_flow
from .config import CODING_GUIDELINE_LABEL, TRANSITION_NOTICE_MARKER_PREFIX
from .review_state import (
    accept_channel_event,
    clear_current_cycle_reviewer_handoff,
    ensure_review_entry,
    mark_review_complete,
    record_transition_notice_sent,
)
from .reviews import rebuild_pr_approval_state


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


@dataclass(frozen=True)
class HeadObservation:
    issue_number: int
    live_state: str
    live_head_sha: str | None
    stored_head_sha: str | None
    contributor_revision_head_sha: str | None


@dataclass(frozen=True)
class HeadObservationRepairDecision:
    should_update_active_head: bool
    should_record_contributor_revision: bool
    should_clear_handoff: bool
    should_clear_completion: bool
    semantic_key: str | None
    outcome: str
    reason: str | None


@dataclass(frozen=True)
class HeadObservationRepairResult:
    changed: bool
    outcome: str
    failure_kind: str | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.changed

    def to_output(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "outcome": self.outcome,
            "failure_kind": self.failure_kind,
            "reason": self.reason,
        }


def derive_head_observation_repair_decision(observation: HeadObservation) -> HeadObservationRepairDecision:
    if observation.live_state.lower() != "open":
        return HeadObservationRepairDecision(False, False, False, False, None, "skipped_not_open", "pull_request_not_open")
    if not observation.live_head_sha:
        return HeadObservationRepairDecision(False, False, False, False, None, "invalid_live_payload", "pull_request_head_unavailable")
    if observation.live_head_sha == observation.stored_head_sha:
        return HeadObservationRepairDecision(False, False, False, False, None, "unchanged", None)
    return HeadObservationRepairDecision(
        should_update_active_head=True,
        should_record_contributor_revision=observation.live_head_sha != observation.contributor_revision_head_sha,
        should_clear_handoff=True,
        should_clear_completion=True,
        semantic_key=f"pull_request_head_observed:{observation.issue_number}:{observation.live_head_sha}",
        outcome="changed",
        reason="live_head_differs_from_stored_head",
    )


def apply_head_observation_repair(review_data: dict, decision: HeadObservationRepairDecision, *, timestamp: str) -> bool:
    if not decision.should_update_active_head or decision.semantic_key is None:
        return False
    head_sha = decision.semantic_key.rsplit(":", 1)[-1]
    changed = False
    if decision.should_record_contributor_revision:
        changed = accept_channel_event(
            review_data,
            "contributor_revision",
            semantic_key=decision.semantic_key,
            timestamp=timestamp,
            reviewed_head_sha=head_sha,
            source_precedence=0,
        ) or changed
    previous_head = review_data.get("active_head_sha")
    review_data["active_head_sha"] = head_sha
    changed = previous_head != head_sha or changed
    if decision.should_clear_handoff:
        changed = clear_current_cycle_reviewer_handoff(review_data) or changed
    if decision.should_clear_completion:
        for key in (
            "current_cycle_completion",
            "current_cycle_write_approval",
            "review_completed_at",
            "review_completed_by",
            "review_completion_source",
        ):
            before = deepcopy(review_data.get(key))
            review_data[key] = {} if key.startswith("current_cycle_") else None
            changed = before != review_data.get(key) or changed
    return changed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def _normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def handle_transition_notice(bot, state: dict, issue_number: int, reviewer: str) -> bool:
    from .overdue import (
        _clear_transport_failure,
        _record_transport_failure,
        find_existing_transition_notice_result,
    )

    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    if review_data.get("transition_notice_sent_at"):
        return False
    existing_notice = find_existing_transition_notice_result(
        bot,
        issue_number,
        review_data.get("transition_warning_sent"),
        reviewer,
    )
    if existing_notice.get("status") == "unavailable":
        if existing_notice.get("failure_kind") in {"unauthorized", "forbidden"}:
            raise RuntimeError(
                f"Permission denied reading transition dedupe comments for #{issue_number} (status {existing_notice.get('status_code')})."
            )
        return _record_transport_failure(
            bot,
            review_data,
            issue_number,
            phase="transition_dedupe_read",
            result=bot.GitHubApiResult(
                existing_notice.get("status_code"),
                None,
                {},
                "",
                False,
                existing_notice.get("failure_kind"),
                existing_notice.get("retry_attempts", 0),
                None,
            ),
        )
    changed = _clear_transport_failure(bot, review_data, issue_number, phase="transition_dedupe_read")
    timestamp = existing_notice.get("timestamp") if existing_notice.get("status") == "found" else None
    if isinstance(timestamp, str) and timestamp:
        record_transition_notice_sent(review_data, timestamp)
        bot.collect_touched_item(issue_number)
        return True
    notice_message = f"""<!-- {TRANSITION_NOTICE_MARKER_PREFIX} issue={issue_number} reviewer={reviewer} -->

🔔 **Transition Period Ended**

@{reviewer}, the {bot.TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

You may still continue this review, or use `{bot.BOT_MENTION} /pass`, `{bot.BOT_MENTION} /release`, or `{bot.BOT_MENTION} /away` if you need to step back.

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    post_result = bot.github.post_comment_result(issue_number, notice_message)
    if not post_result.ok:
        if post_result.failure_kind in {"unauthorized", "forbidden"}:
            raise RuntimeError(
                f"Permission denied posting transition notice for #{issue_number} (status {post_result.status_code})."
            )
        if (
            post_result.failure_kind in {"invalid_payload", "server_error", "transport_error", "rate_limited"}
            or (post_result.status_code is not None and post_result.status_code < 400)
        ):
            existing_notice = find_existing_transition_notice_result(
                bot,
                issue_number,
                review_data.get("transition_warning_sent"),
                reviewer,
            )
            timestamp = existing_notice.get("timestamp") if existing_notice.get("status") == "found" else None
            if isinstance(timestamp, str) and timestamp:
                record_transition_notice_sent(review_data, timestamp)
                _clear_transport_failure(bot, review_data, issue_number, phase="transition_post")
                bot.collect_touched_item(issue_number)
                return True
        return _record_transport_failure(bot, review_data, issue_number, phase="transition_post", result=post_result)
    changed = _clear_transport_failure(bot, review_data, issue_number, phase="transition_post") or changed
    record_transition_notice_sent(
        review_data,
        bot.datetime.now(bot.timezone.utc).isoformat(),
    )
    bot.collect_touched_item(issue_number)
    return True


def _tracked_review_issue(bot, labels: list[str]) -> bool:
    return any(label in bot.REVIEW_LABELS for label in labels)


def _reconcile_lifecycle_reviewer_authority(
    bot,
    state: dict,
    request,
    *,
    assignment_method: str,
    allow_auto_assign: bool,
) -> bool:
    issue_number = request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    labels = list(request.issue_labels)
    if not _tracked_review_issue(bot, labels):
        return False
    current_assignees = bot.github.get_issue_assignees(issue_number)
    if current_assignees is None:
        raise RuntimeError(f"Unable to determine assignees for #{issue_number}")
    if not request.event_created_at:
        raise RuntimeError(f"Missing lifecycle timestamp for {request.event_action} event")
    cycle_started_at = request.event_created_at
    if len(current_assignees) == 1:
        reviewer = current_assignees[0]
        if request.issue_author and reviewer.lower() == request.issue_author.lower():
            return assignment_flow.clear_reviewer_authority(bot, state, issue_number, reason="self_review_not_allowed")
        result = assignment_flow.confirm_reviewer_assignment(
            bot,
            state,
            request,
            reviewer=reviewer,
            assignment_method=assignment_method,
            cycle_started_at=cycle_started_at,
            current_assignees=current_assignees,
            record_assignment=False,
            emit_guidance=False,
            emit_failure_comment=False,
            pr_head_sha=request.pr_head_sha,
        )
        return bool(
            result.get("confirmed")
            or result.get("cleared_current_reviewer")
            or result.get("diagnostic_changed")
        )
    if len(current_assignees) > 1:
        return assignment_flow.clear_reviewer_authority(bot, state, issue_number, reason="multiple_live_assignees")
    if not allow_auto_assign:
        return assignment_flow.clear_reviewer_authority(bot, state, issue_number, reason="no_live_assignees")
    reviewer = bot.adapters.queue.get_next_reviewer(
        state,
        skip_usernames={request.issue_author} if request.issue_author else set(),
    )
    if not reviewer:
        bot.github.post_comment(
            issue_number,
            f"⚠️ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue.",
        )
        return False
    result = assignment_flow.confirm_reviewer_assignment(
        bot,
        state,
        request,
        reviewer=reviewer,
        assignment_method="round-robin",
        cycle_started_at=cycle_started_at,
        current_assignees=current_assignees,
        record_assignment=True,
        emit_guidance=True,
        emit_failure_comment=True,
        pr_head_sha=request.pr_head_sha,
    )
    return bool(
        result.get("confirmed")
        or result.get("cleared_current_reviewer")
        or result.get("diagnostic_changed")
    )


def _clear_completion(review_data: dict) -> bool:
    changed = False
    if review_data.get("review_completed_at") is not None:
        review_data["review_completed_at"] = None
        changed = True
    if review_data.get("review_completed_by") is not None:
        review_data["review_completed_by"] = None
        changed = True
    if review_data.get("review_completion_source") is not None:
        review_data["review_completion_source"] = None
        changed = True
    if review_data.get("current_cycle_completion"):
        review_data["current_cycle_completion"] = {}
        changed = True
    return changed


def handle_issue_or_pr_opened(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_or_pr_opened")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    issue_key = str(request.issue_number)
    tracked_reviewer = None
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    if tracked_reviewer:
        return False
    return _reconcile_lifecycle_reviewer_authority(
        bot,
        state,
        request,
        assignment_method="lifecycle-opened",
        allow_auto_assign=True,
    )


def handle_issue_edited_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_edited_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    if request.is_pull_request:
        return False
    issue_number = request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_author = request.issue_author
    editor = request.sender_login or issue_author
    if not issue_author or editor.lower() != issue_author.lower():
        return False
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    if not request.event_created_at:
        raise RuntimeError("Missing lifecycle timestamp for edited event")
    updated_at = request.event_created_at
    current_title = request.issue_title
    current_body = request.issue_body
    previous_title = request.previous_title
    previous_body = request.previous_body
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
    return accept_channel_event(
        review_data,
        "contributor_comment",
        semantic_key=semantic_key,
        timestamp=updated_at,
        actor=issue_author,
        source_precedence=0,
    )


def handle_labeled_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_labeled_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    issue_number = request.issue_number
    if not issue_number:
        return False
    label_name = request.label_name
    is_pr = request.is_pull_request
    bot.collect_touched_item(issue_number)
    if label_name == "sign-off: create pr":
        if is_pr:
            return False
        if CODING_GUIDELINE_LABEL not in set(request.issue_labels):
            return False
        review_data = ensure_review_entry(state, issue_number)
        reviewer = review_data.get("current_reviewer") if review_data else None
        return mark_review_complete(state, issue_number, reviewer, "issue_label: sign-off: create pr")
    if label_name not in bot.REVIEW_LABELS:
        return False
    return handle_issue_or_pr_opened(bot, state)


def handle_unlabeled_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_unlabeled_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    if not request.issue_number:
        return False
    bot.collect_touched_item(request.issue_number)
    changed = False
    review_data = ensure_review_entry(state, request.issue_number)
    if (
        request.label_name == "sign-off: create pr"
        and isinstance(review_data, dict)
        and review_data.get("review_completion_source") == "issue_label: sign-off: create pr"
    ):
        changed = _clear_completion(review_data) or changed
    if request.label_name in bot.REVIEW_LABELS and not _tracked_review_issue(bot, list(request.issue_labels)):
        changed = assignment_flow.clear_reviewer_authority(bot, state, request.issue_number, reason="review_label_removed") or changed
    return changed


def handle_assigned_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_assigned_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    return _reconcile_lifecycle_reviewer_authority(
        bot,
        state,
        request,
        assignment_method="lifecycle-assigned",
        allow_auto_assign=False,
    )


def handle_unassigned_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_unassigned_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    return _reconcile_lifecycle_reviewer_authority(
        bot,
        state,
        request,
        assignment_method="lifecycle-unassigned",
        allow_auto_assign=False,
    )


def handle_reopened_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_reopened_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    changed = _reconcile_lifecycle_reviewer_authority(
        bot,
        state,
        request,
        assignment_method="lifecycle-reopened",
        allow_auto_assign=False,
    )
    review_data = ensure_review_entry(state, request.issue_number)
    if isinstance(review_data, dict) and review_data.get("review_completion_source") != "issue_label: sign-off: create pr":
        changed = _clear_completion(review_data) or changed
    return changed


def handle_pull_request_target_synchronize(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_pull_request_target_synchronize")
    from .event_inputs import build_pull_request_sync_request

    if _runtime_epoch(state) != "freshness_v15":
        _log(bot, "info", "V18 synchronize repair safe-noop before epoch flip")
        return False
    request = build_pull_request_sync_request(bot)
    issue_number = request.issue_number
    if not issue_number:
        return False
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None or not review_data.get("current_reviewer"):
        return False
    head_sha = request.head_sha
    if not head_sha:
        raise RuntimeError("Missing PR_HEAD_SHA for synchronize event")
    if not request.event_created_at:
        raise RuntimeError("Missing lifecycle timestamp for synchronize event")
    bot.collect_touched_item(issue_number)
    previous_head_sha = review_data.get("active_head_sha")
    previous_completion = deepcopy(review_data.get("current_cycle_completion"))
    previous_write_approval = deepcopy(review_data.get("current_cycle_write_approval"))
    previous_review_completed_at = review_data.get("review_completed_at")
    previous_review_completed_by = review_data.get("review_completed_by")
    previous_review_completion_source = review_data.get("review_completion_source")
    review_data["active_head_sha"] = head_sha
    handoff_changed = False
    if previous_head_sha != head_sha:
        handoff_changed = clear_current_cycle_reviewer_handoff(review_data)
    timestamp = request.event_created_at
    changed = accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=f"pull_request_sync:{issue_number}:{head_sha}",
        timestamp=timestamp,
        reviewed_head_sha=head_sha,
        source_precedence=1,
    )
    rebuild_pr_approval_state(bot, issue_number, review_data)
    approval_changed = (
        previous_completion != review_data.get("current_cycle_completion")
        or previous_write_approval != review_data.get("current_cycle_write_approval")
        or previous_review_completed_at != review_data.get("review_completed_at")
        or previous_review_completed_by != review_data.get("review_completed_by")
        or previous_review_completion_source != review_data.get("review_completion_source")
    )
    return changed or previous_head_sha != review_data.get("active_head_sha") or approval_changed or handoff_changed


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
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    observation = HeadObservation(
        issue_number=issue_number,
        live_state=str(pull_request.get("state", "")),
        live_head_sha=head_sha,
        stored_head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
        contributor_revision_head_sha=(
            contributor_revision.get("reviewed_head_sha") if isinstance(contributor_revision, dict) else None
        ),
    )
    decision = derive_head_observation_repair_decision(observation)
    if decision.outcome == "unchanged":
        return HeadObservationRepairResult(changed=False, outcome="unchanged")
    if not decision.should_record_contributor_revision:
        review_data["active_head_sha"] = head_sha
        clear_current_cycle_reviewer_handoff(review_data)
        return HeadObservationRepairResult(changed=True, outcome="changed")
    changed = apply_head_observation_repair(review_data, decision, timestamp=_now_iso())
    return HeadObservationRepairResult(changed=changed, outcome="changed" if changed else "unchanged")


def handle_closed_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_closed_event")
    from .event_inputs import build_issue_lifecycle_request

    request = build_issue_lifecycle_request(bot)
    issue_number = request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    return remove_closed_review_entry(bot, state, issue_number, reason="closed_event")


def remove_closed_review_entry(bot, state: dict, issue_number: int, *, reason: str) -> bool:
    issue_key = str(issue_number)
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        _log(
            bot,
            "info",
            f"Removed active review row for closed item #{issue_number}",
            issue_number=issue_number,
            reason=reason,
        )
        bot.collect_touched_item(issue_number)
        return True
    return False
