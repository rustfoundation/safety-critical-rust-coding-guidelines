"""Overdue review domain logic for reviewer-bot."""

from __future__ import annotations

from dataclasses import dataclass

from . import assignment_flow
from .config import TRANSITION_NOTICE_MARKER_PREFIX, TRANSITION_WARNING_MARKER_PREFIX
from .reminder_comments import ReminderCommentScan
from .repair_records import clear_repair_marker, store_repair_marker

_TRANSITION_NOTICE_AUTHORS = {"github-actions[bot]", "guidelines-bot"}


@dataclass(frozen=True)
class ReminderScopeReceipt:
    issue_number: int
    reviewer: str | None
    head_sha: str | None
    cycle_key: str | None
    scope_key: str | None
    receipt_kind: str
    comment_id: int | str | None
    created_at: str | None
    source: str
    status: str
    reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "reviewer": self.reviewer,
            "head_sha": self.head_sha,
            "cycle_key": self.cycle_key,
            "scope_key": self.scope_key,
            "receipt_kind": self.receipt_kind,
            "comment_id": self.comment_id,
            "created_at": self.created_at,
            "source": self.source,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LegacyReminderFieldAuthority:
    transition_warning_sent: str | None
    transition_notice_sent_at: str | None
    warning_scope_status: str
    transition_scope_status: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "transition_warning_sent": self.transition_warning_sent,
            "transition_notice_sent_at": self.transition_notice_sent_at,
            "warning_scope_status": self.warning_scope_status,
            "transition_scope_status": self.transition_scope_status,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class ReminderDeliveryPersistenceResult:
    issue_number: int
    reviewer: str | None
    head_sha: str | None
    cycle_key: str | None
    scope_key: str | None
    receipt_kind: str
    comment_posted: bool
    comment_id: int | str | None
    comment_created_at: str | None
    state_save_attempted: bool
    state_save_succeeded: bool
    recovery_required: bool
    recovered_receipt: dict[str, object] | None
    result: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "reviewer": self.reviewer,
            "head_sha": self.head_sha,
            "cycle_key": self.cycle_key,
            "scope_key": self.scope_key,
            "receipt_kind": self.receipt_kind,
            "comment_posted": self.comment_posted,
            "comment_id": self.comment_id,
            "comment_created_at": self.comment_created_at,
            "state_save_attempted": self.state_save_attempted,
            "state_save_succeeded": self.state_save_succeeded,
            "recovery_required": self.recovery_required,
            "recovered_receipt": self.recovered_receipt,
            "result": self.result,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class ReminderCadenceDecision:
    issue_number: int
    reviewer: str | None
    scope: object | None
    cadence_state: str
    exhaustion_reason: str | None
    warning_receipt: ReminderScopeReceipt | None
    transition_receipt: ReminderScopeReceipt | None
    legacy_duplicate_count: int
    may_post_warning: bool
    may_post_transition: bool
    must_project_reassignment_needed: bool

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "reviewer": self.reviewer,
            "scope": self.scope.to_output() if hasattr(self.scope, "to_output") else None,
            "cadence_state": self.cadence_state,
            "exhaustion_reason": self.exhaustion_reason,
            "warning_receipt": self.warning_receipt.to_output() if self.warning_receipt else None,
            "transition_receipt": self.transition_receipt.to_output() if self.transition_receipt else None,
            "legacy_duplicate_count": self.legacy_duplicate_count,
            "may_post_warning": self.may_post_warning,
            "may_post_transition": self.may_post_transition,
            "must_project_reassignment_needed": self.must_project_reassignment_needed,
        }


@dataclass(frozen=True)
class OverdueReminderDecision:
    issue_number: int
    reviewer: str | None
    action: str
    anchor_timestamp: str | None
    anchor_reason: str | None
    scope: object | None
    receipt: ReminderScopeReceipt | None
    dedupe_marker: str | None
    reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "reviewer": self.reviewer,
            "action": self.action,
            "anchor_timestamp": self.anchor_timestamp,
            "anchor_reason": self.anchor_reason,
            "scope": self.scope.to_output() if hasattr(self.scope, "to_output") else None,
            "receipt": self.receipt.to_output() if self.receipt else None,
            "dedupe_marker": self.dedupe_marker,
            "reason": self.reason,
        }


def derive_reminder_scope_receipt(
    *,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
    persisted_state: dict,
    scanned_comments: tuple[object, ...] = (),
) -> ReminderScopeReceipt:
    warning = persisted_state.get("transition_warning_sent") if isinstance(persisted_state, dict) else None
    notice = persisted_state.get("transition_notice_sent_at") if isinstance(persisted_state, dict) else None
    if isinstance(notice, str) and notice.strip():
        return ReminderScopeReceipt(issue_number, reviewer, head_sha, cycle_key, scope_key, "transition", None, notice, "state", "found", None)
    if isinstance(warning, str) and warning.strip():
        return ReminderScopeReceipt(issue_number, reviewer, head_sha, cycle_key, scope_key, "warning", None, warning, "state", "found", None)
    if scanned_comments:
        record = sorted(scanned_comments, key=lambda item: getattr(item, "created_at", ""))[-1]
        shape = getattr(record, "matched_shape", "")
        kind = "legacy_transition" if "transition" in shape else "legacy_warning_or_reminder"
        return ReminderScopeReceipt(
            issue_number,
            reviewer,
            head_sha,
            cycle_key,
            scope_key,
            kind,
            getattr(record, "comment_id", None),
            getattr(record, "created_at", None),
            "comment_scan",
            "found",
            None,
        )
    return ReminderScopeReceipt(issue_number, reviewer, head_sha, cycle_key, scope_key, "none", None, None, "derived_absent", "missing", None)


def classify_legacy_reminder_field_authority(
    *,
    transition_warning_sent: object,
    transition_notice_sent_at: object,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
) -> LegacyReminderFieldAuthority:
    del issue_number, reviewer, head_sha, cycle_key, scope_key
    warning = transition_warning_sent if isinstance(transition_warning_sent, str) and transition_warning_sent.strip() else None
    notice = transition_notice_sent_at if isinstance(transition_notice_sent_at, str) and transition_notice_sent_at.strip() else None
    warning_status = "legacy_scope_unbound" if warning else "ignored_stale_scope"
    transition_status = "legacy_scope_unbound" if notice else "ignored_stale_scope"
    if warning and notice:
        transition_status = "legacy_duplicate_exhausted"
    return LegacyReminderFieldAuthority(warning, notice, warning_status, transition_status, None)


def build_reminder_delivery_persistence_result(
    *,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
    receipt_kind: str,
    comment_posted: bool,
    comment_id: int | str | None,
    comment_created_at: str | None,
    state_save_attempted: bool,
    state_save_succeeded: bool,
    recovered_receipt: ReminderScopeReceipt | None = None,
    diagnostic_reason: str | None = None,
) -> ReminderDeliveryPersistenceResult:
    if comment_posted and state_save_attempted and not state_save_succeeded:
        result = "posted_save_failed_recoverable" if recovered_receipt is not None else "posted_save_failed_unrecoverable"
    elif recovered_receipt is not None and not comment_posted:
        result = "not_posted_existing_receipt"
    elif state_save_succeeded or not state_save_attempted:
        result = "persisted"
    else:
        result = "blocked"
    return ReminderDeliveryPersistenceResult(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=head_sha,
        cycle_key=cycle_key,
        scope_key=scope_key,
        receipt_kind=receipt_kind,
        comment_posted=comment_posted,
        comment_id=comment_id,
        comment_created_at=comment_created_at,
        state_save_attempted=state_save_attempted,
        state_save_succeeded=state_save_succeeded,
        recovery_required=result.startswith("posted_save_failed"),
        recovered_receipt=recovered_receipt.to_output() if recovered_receipt else None,
        result=result,
        diagnostic_reason=diagnostic_reason,
    )


def derive_reminder_cadence_decision(
    response,
    *,
    receipt: ReminderScopeReceipt | None,
    reminder_scan: ReminderCommentScan | None,
    now: object,
    review_deadline_days: int,
    transition_period_days: int,
) -> ReminderCadenceDecision:
    del now, review_deadline_days, transition_period_days
    issue_number = int(getattr(response, "scope", None).issue_number or 0) if getattr(response, "scope", None) else 0
    reviewer = getattr(getattr(response, "scope", None), "reviewer", None)
    legacy_duplicate_count = reminder_scan.baseline_count if reminder_scan is not None else 0
    exhausted = (receipt is not None and receipt.receipt_kind in {"transition", "legacy_transition"}) or legacy_duplicate_count >= 2
    return ReminderCadenceDecision(
        issue_number=issue_number,
        reviewer=reviewer,
        scope=getattr(response, "scope", None),
        cadence_state="exhausted" if exhausted else "not_started",
        exhaustion_reason="legacy_duplicate_reminders_exhausted" if legacy_duplicate_count >= 2 else "transition_notice_sent" if exhausted else "not_exhausted",
        warning_receipt=receipt if receipt and receipt.receipt_kind in {"warning", "legacy_warning_or_reminder"} else None,
        transition_receipt=receipt if receipt and receipt.receipt_kind in {"transition", "legacy_transition"} else None,
        legacy_duplicate_count=legacy_duplicate_count,
        may_post_warning=not exhausted and receipt is None,
        may_post_transition=not exhausted and receipt is not None and receipt.receipt_kind == "warning",
        must_project_reassignment_needed=exhausted,
    )


def decide_overdue_reminder(
    response,
    *,
    cadence: ReminderCadenceDecision,
    now: object,
    review_deadline_days: int,
    transition_period_days: int,
) -> OverdueReminderDecision:
    del now, review_deadline_days, transition_period_days
    if getattr(response, "response_state", None) != "awaiting_reviewer_response" or cadence.must_project_reassignment_needed:
        action = "none"
        reason = cadence.exhaustion_reason or "not_awaiting_reviewer_response"
    elif cadence.may_post_transition:
        action = "transition"
        reason = "transition_due"
    elif cadence.may_post_warning:
        action = "warning"
        reason = "warning_due"
    else:
        action = "none"
        reason = "existing_receipt"
    return OverdueReminderDecision(
        issue_number=cadence.issue_number,
        reviewer=cadence.reviewer,
        action=action,
        anchor_timestamp=getattr(response, "anchor_timestamp", None),
        anchor_reason=getattr(response, "reason", None),
        scope=cadence.scope,
        receipt=cadence.transition_receipt or cadence.warning_receipt,
        dedupe_marker=None,
        reason=reason,
    )


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _warning_anchor_sentence(bot, reviewer: str, anchor_reason: str | None) -> str:
    if anchor_reason in {"contributor_comment_newer", "contributor_revision_newer"}:
        return (
            f"Hey @{reviewer}, it's been more than {bot.REVIEW_DEADLINE_DAYS} days since the latest "
            "contributor follow-up returned this review to you."
        )
    return f"Hey @{reviewer}, it's been more than {bot.REVIEW_DEADLINE_DAYS} days since you were assigned to review this."


def _transport_marker(*, phase: str, result, recorded_at: str) -> dict:
    return {
        "kind": "reminder_transport_failure",
        "phase": phase,
        "status_code": result.status_code,
        "failure_kind": result.failure_kind,
        "retry_attempts": result.retry_attempts,
        "recorded_at": recorded_at,
    }


def _record_transport_failure(bot, review_data: dict, issue_number: int, *, phase: str, result) -> bool:
    changed = store_repair_marker(
        review_data,
        phase,
        _transport_marker(phase=phase, result=result, recorded_at=bot.clock.now().isoformat()),
    )
    if changed:
        bot.collect_touched_item(issue_number)
    return changed


def _clear_transport_failure(bot, review_data: dict, issue_number: int, *, phase: str) -> bool:
    changed = clear_repair_marker(review_data, phase)
    if changed:
        bot.collect_touched_item(issue_number)
    return changed


def _warning_marker(issue_number: int, reviewer: str, anchor_timestamp: str | None) -> str:
    return (
        f"<!-- {TRANSITION_WARNING_MARKER_PREFIX} issue={issue_number} reviewer={reviewer} "
        f"anchor={anchor_timestamp or ''} -->"
    )


def _warning_scope_marker(current_scope_key: str | None, current_scope_basis: str | None) -> str | None:
    if not isinstance(current_scope_key, str) or not current_scope_key:
        return None
    if not isinstance(current_scope_basis, str) or not current_scope_basis:
        return None
    return (
        "<!-- reviewer-bot:transition-warning-scope:v1 "
        f"basis={current_scope_basis} key={current_scope_key} -->"
    )


def _authority_marker(*, phase: str, live_assignees: list[str], reason: str, recorded_at: str) -> dict:
    return {
        "kind": "reviewer_authority_mismatch",
        "phase": phase,
        "status_code": None,
        "failure_kind": "reviewer_authority_mismatch",
        "retry_attempts": 0,
        "recorded_at": recorded_at,
        "reason": reason,
        "live_assignees": list(live_assignees),
    }


def _find_existing_marker_comment(
    bot,
    issue_number: int,
    marker: str,
    *,
    authors: set[str],
    not_before: str | None = None,
) -> dict[str, object]:
    earliest = None
    if isinstance(not_before, str) and not_before:
        try:
            earliest = bot.datetime.fromisoformat(not_before.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            earliest = None
    page = 1
    while True:
        response = bot.github.list_issue_comments_result(issue_number, page=page)
        if not response.ok or not isinstance(response.payload, list):
            return {
                "status": "unavailable",
                "status_code": response.status_code,
                "failure_kind": response.failure_kind,
                "retry_attempts": response.retry_attempts,
            }
        first_match = None
        for comment in response.payload:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            created_at = comment.get("created_at")
            body = comment.get("body")
            if not isinstance(login, str) or not isinstance(created_at, str) or not isinstance(body, str):
                continue
            if login not in authors:
                continue
            try:
                created_dt = bot.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if earliest is not None and created_dt < earliest:
                continue
            lines = body.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line == marker:
                if first_match is None or created_dt < first_match[0]:
                    first_match = (created_dt, created_at)
        if first_match is not None:
            return {"status": "found", "timestamp": first_match[1]}
        if len(response.payload) < 100:
            break
        page += 1
    return {"status": "missing"}


def _warning_scan_result(bot, issue_number: int, reviewer: str, anchor_timestamp: str | None) -> dict[str, object]:
    return _find_existing_warning_comment(bot, issue_number, reviewer, anchor_timestamp)


def _find_existing_warning_comment(
    bot,
    issue_number: int,
    reviewer: str,
    anchor_timestamp: str | None,
    *,
    current_scope_key: str | None = None,
    current_scope_basis: str | None = None,
) -> dict[str, object]:
    legacy_marker = _warning_marker(issue_number, reviewer, anchor_timestamp)
    scope_marker = _warning_scope_marker(current_scope_key, current_scope_basis)
    scope_prefix = "<!-- reviewer-bot:transition-warning-scope:v1 "
    page = 1
    while True:
        response = bot.github.list_issue_comments_result(issue_number, page=page)
        if not response.ok or not isinstance(response.payload, list):
            return {
                "status": "unavailable",
                "status_code": response.status_code,
                "failure_kind": response.failure_kind,
                "retry_attempts": response.retry_attempts,
            }
        first_match = None
        for comment in response.payload:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            created_at = comment.get("created_at")
            body = comment.get("body")
            if not isinstance(login, str) or not isinstance(created_at, str) or not isinstance(body, str):
                continue
            if login not in _TRANSITION_NOTICE_AUTHORS:
                continue
            lines = body.splitlines()
            first_line = lines[0].strip() if lines else ""
            second_line = lines[1].strip() if len(lines) > 1 else ""
            if first_line != legacy_marker:
                continue
            if second_line.startswith(scope_prefix):
                if scope_marker is None or second_line != scope_marker:
                    continue
            try:
                created_dt = bot.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if first_match is None or created_dt < first_match[0]:
                first_match = (created_dt, created_at)
        if first_match is not None:
            return {"status": "found", "timestamp": first_match[1]}
        if len(response.payload) < 100:
            break
        page += 1
    return {"status": "missing"}


def _transport_result(bot, *, failure_kind: str | None, status_code: int | None = None):
    return bot.GitHubApiResult(
        status_code,
        None,
        {},
        "",
        False,
        failure_kind,
        0,
        None,
    )


def evaluate_overdue_review_preview(bot, state: dict, issue_number: int) -> dict[str, object]:
    active_reviews = state.get("active_reviews") if isinstance(state, dict) else None
    review_data = active_reviews.get(str(issue_number)) if isinstance(active_reviews, dict) else None
    if not isinstance(review_data, dict):
        review_data = {}
    issue_snapshot_result = bot.github.get_issue_or_pr_snapshot_result(issue_number)
    issue_snapshot = issue_snapshot_result.payload if issue_snapshot_result.ok and isinstance(issue_snapshot_result.payload, dict) else None
    is_pull_request = isinstance((issue_snapshot or {}).get("pull_request"), dict)
    authority = assignment_flow.resolve_reviewer_authority(
        bot,
        issue_number,
        review_data,
        is_pull_request=is_pull_request,
    )
    response_state = bot.adapters.review_state.compute_reviewer_response_state(
        issue_number,
        review_data,
        issue_snapshot=issue_snapshot,
    )
    response_name = str(response_state.get("response_state") or response_state.get("state") or "projection_failed")
    current_scope_key = response_state.get("current_scope_key") if isinstance(response_state.get("current_scope_key"), str) else None
    current_scope_basis = response_state.get("current_scope_basis") if isinstance(response_state.get("current_scope_basis"), str) else None
    suppression_reason = response_state.get("suppression_reason") if response_state.get("suppression_reason") is not None else None
    preview = {
        "response_state": response_name,
        "reviewer_authority_outcome": authority["authority_status"],
        "suppression_reason": suppression_reason,
        "current_scope_key": current_scope_key,
        "current_scope_basis": current_scope_basis,
        "would_post_warning": False,
        "would_post_transition": False,
    }
    if authority["authority_status"] != "tracked_reviewer_confirmed":
        return preview
    if response_name != "awaiting_reviewer_response":
        return preview
    current_reviewer = review_data.get("current_reviewer")
    anchor_timestamp = response_state.get("anchor_timestamp") if isinstance(response_state.get("anchor_timestamp"), str) else None
    if not isinstance(current_reviewer, str) or not current_reviewer.strip() or not isinstance(anchor_timestamp, str) or not anchor_timestamp:
        return preview
    try:
        now = bot.datetime.now(bot.timezone.utc)
        anchor_dt = bot.datetime.fromisoformat(anchor_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return preview
    transition_warning_sent = review_data.get("transition_warning_sent")
    if isinstance(transition_warning_sent, str) and transition_warning_sent:
        try:
            warning_dt = bot.datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return preview
        if (now - warning_dt).days < bot.TRANSITION_PERIOD_DAYS:
            return preview
        existing_notice = find_existing_transition_notice_result(
            bot,
            issue_number,
            transition_warning_sent,
            current_reviewer,
        )
        preview["would_post_transition"] = existing_notice.get("status") == "missing"
        return preview
    if (now - anchor_dt).days < bot.REVIEW_DEADLINE_DAYS:
        return preview
    existing_warning = _find_existing_warning_comment(
        bot,
        issue_number,
        current_reviewer,
        anchor_timestamp,
        current_scope_key=current_scope_key,
        current_scope_basis=current_scope_basis,
    )
    preview["would_post_warning"] = existing_warning.get("status") == "missing"
    return preview


def check_overdue_reviews_result(bot, state: dict) -> tuple[list[dict], bool]:
    overdue = check_overdue_reviews(bot, state)
    return overdue, False


def check_overdue_reviews(bot, state: dict) -> list[dict]:
    """Check all active reviews for overdue ones."""
    if "active_reviews" not in state:
        return []

    now = bot.datetime.now(bot.timezone.utc)
    overdue = []

    for issue_key, review_data in state["active_reviews"].items():
        if not isinstance(review_data, dict):
            continue

        if review_data.get("review_completed_at"):
            continue

        if review_data.get("transition_notice_sent_at"):
            continue

        current_reviewer = review_data.get("current_reviewer")
        if not current_reviewer:
            continue

        issue_number = int(issue_key)
        issue_snapshot_result = bot.github.get_issue_or_pr_snapshot_result(issue_number)
        issue_snapshot = issue_snapshot_result.payload if issue_snapshot_result.ok else None
        if not isinstance(issue_snapshot, dict):
            if issue_snapshot_result.failure_kind in {"unauthorized", "forbidden"}:
                raise RuntimeError(
                    f"Permission denied reading issue snapshot for #{issue_number} (status {issue_snapshot_result.status_code})."
                )
            _record_transport_failure(
                bot,
                review_data,
                issue_number,
                phase="issue_snapshot_read",
                result=issue_snapshot_result,
            )
            _log(bot, "warning", f"Skipping overdue evaluation for #{issue_number}; issue/PR snapshot unavailable", issue_number=issue_number)
            continue
        _clear_transport_failure(bot, review_data, issue_number, phase="issue_snapshot_read")
        if str(issue_snapshot.get("state", "")).lower() == "closed":
            continue
        authority = assignment_flow.resolve_reviewer_authority(
            bot,
            issue_number,
            review_data,
            is_pull_request=isinstance(issue_snapshot.get("pull_request"), dict),
        )
        if authority["authority_status"] == "live_read_unavailable":
            _record_transport_failure(
                bot,
                review_data,
                issue_number,
                phase="assignment_confirm_read",
                result=_transport_result(bot, failure_kind=str(authority.get("reason") or "transport_error")),
            )
            continue
        if authority["authority_status"] == "control_plane_mismatch":
            _store_assignment_marker = store_repair_marker(
                review_data,
                "assignment_confirm_read",
                _authority_marker(
                    phase="assignment_confirm_read",
                    live_assignees=list(authority.get("live_control_plane_reviewers") or []),
                    reason=str(authority.get("reason") or "tracked_reviewer_missing_from_live_control_plane"),
                    recorded_at=bot.clock.now().isoformat(),
                ),
            )
            if _store_assignment_marker:
                bot.collect_touched_item(issue_number)
            continue
        if authority["authority_status"] != "tracked_reviewer_confirmed":
            continue
        _clear_transport_failure(bot, review_data, issue_number, phase="assignment_confirm_read")
        response_state = bot.adapters.review_state.compute_reviewer_response_state(
            issue_number,
            review_data,
            issue_snapshot=issue_snapshot,
        )
        response_name = str(response_state.get("response_state") or response_state.get("state") or "")
        if response_name != "awaiting_reviewer_response":
            continue
        last_activity = response_state.get("anchor_timestamp")
        anchor_reason = response_state.get("reason") if isinstance(response_state.get("reason"), str) else None
        current_scope_key = response_state.get("current_scope_key") if isinstance(response_state.get("current_scope_key"), str) else None
        current_scope_basis = response_state.get("current_scope_basis") if isinstance(response_state.get("current_scope_basis"), str) else None

        if not last_activity:
            continue

        try:
            last_activity_dt = bot.datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        days_since_activity = (now - last_activity_dt).days

        if days_since_activity < bot.REVIEW_DEADLINE_DAYS:
            continue

        transition_warning_sent = review_data.get("transition_warning_sent")
        if transition_warning_sent:
            try:
                warning_dt = bot.datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
                days_since_warning = (now - warning_dt).days

                if days_since_warning >= bot.TRANSITION_PERIOD_DAYS:
                    overdue.append(
                        {
                            "issue_number": issue_number,
                            "reviewer": current_reviewer,
                            "days_overdue": days_since_activity,
                            "days_since_warning": days_since_warning,
                            "needs_warning": False,
                            "needs_transition": True,
                            "anchor_reason": anchor_reason,
                            "anchor_timestamp": last_activity,
                            "current_scope_key": current_scope_key,
                            "current_scope_basis": current_scope_basis,
                        }
                    )
            except (ValueError, AttributeError):
                pass
        else:
            overdue.append(
                {
                    "issue_number": issue_number,
                    "reviewer": current_reviewer,
                    "days_overdue": days_since_activity - bot.REVIEW_DEADLINE_DAYS,
                    "days_since_warning": 0,
                    "needs_warning": True,
                    "needs_transition": False,
                    "anchor_reason": anchor_reason,
                    "anchor_timestamp": last_activity,
                    "current_scope_key": current_scope_key,
                    "current_scope_basis": current_scope_basis,
                }
            )

    return overdue


def find_existing_transition_notice_result(bot, issue_number: int, transition_warning_sent: str | None, reviewer: str | None = None) -> dict[str, object]:
    if not isinstance(transition_warning_sent, str) or not transition_warning_sent:
        return {"status": "missing"}
    return _find_existing_marker_comment(
        bot,
        issue_number,
        f"<!-- {TRANSITION_NOTICE_MARKER_PREFIX} issue={issue_number} reviewer={reviewer or ''} -->",
        authors=_TRANSITION_NOTICE_AUTHORS,
        not_before=transition_warning_sent,
    )


def backfill_transition_notice_if_present(bot, state: dict, issue_number: int) -> bool:
    issue_key = str(issue_number)
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    review_data = active_reviews.get(issue_key)
    if not isinstance(review_data, dict):
        return False
    if review_data.get("transition_notice_sent_at"):
        return False
    existing_notice = find_existing_transition_notice_result(
        bot,
        issue_number,
        review_data.get("transition_warning_sent"),
        review_data.get("current_reviewer"),
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
    if not isinstance(timestamp, str) or not timestamp:
        return changed
    review_data["transition_notice_sent_at"] = timestamp
    bot.collect_touched_item(issue_number)
    return True


def handle_overdue_review_warning(
    bot,
    state: dict,
    issue_number: int,
    reviewer: str,
    *,
    anchor_reason: str | None = None,
    anchor_timestamp: str | None = None,
    current_scope_key: str | None = None,
    current_scope_basis: str | None = None,
) -> bool:
    """Post a warning comment and record that we've warned the reviewer."""
    issue_key = str(issue_number)

    if "active_reviews" not in state or issue_key not in state["active_reviews"]:
        return False

    review_data = state["active_reviews"][issue_key]
    if not isinstance(review_data, dict):
        return False
    existing_warning = _find_existing_warning_comment(
        bot,
        issue_number,
        reviewer,
        anchor_timestamp,
        current_scope_key=current_scope_key,
        current_scope_basis=current_scope_basis,
    )
    if existing_warning.get("status") == "unavailable":
        if existing_warning.get("failure_kind") in {"unauthorized", "forbidden"}:
            raise RuntimeError(
                f"Permission denied reading warning dedupe comments for #{issue_number} (status {existing_warning.get('status_code')})."
            )
        return _record_transport_failure(
            bot,
            review_data,
            issue_number,
            phase="warning_dedupe_read",
            result=bot.GitHubApiResult(
                existing_warning.get("status_code"),
                None,
                {},
                "",
                False,
                existing_warning.get("failure_kind"),
                existing_warning.get("retry_attempts", 0),
                None,
            ),
        )
    changed = _clear_transport_failure(bot, review_data, issue_number, phase="warning_dedupe_read")
    if existing_warning.get("status") == "found":
        review_data["transition_warning_sent"] = existing_warning.get("timestamp")
        bot.collect_touched_item(issue_number)
        return True

    warning_scope_marker = _warning_scope_marker(current_scope_key, current_scope_basis)
    warning_header = _warning_marker(issue_number, reviewer, anchor_timestamp)
    if isinstance(warning_scope_marker, str):
        warning_header = f"{warning_header}\n{warning_scope_marker}"
    warning_message = f"""{warning_header}

⚠️ **Review Reminder**

{_warning_anchor_sentence(bot, reviewer, anchor_reason)}

**Please take one of the following actions:**

1. **Begin your review** - Post a comment with your feedback
2. **Pass the review** - Use `{bot.BOT_MENTION} /pass [reason]` to assign the next reviewer
3. **Step away temporarily** - Use `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]` if you need time off

If no action is taken within {bot.TRANSITION_PERIOD_DAYS} days, you may be transitioned from Producer to Observer status per our [contribution guidelines](CONTRIBUTING.md#review-deadlines).

_Life happens! If you're dealing with something, just let us know._"""

    post_result = bot.github.post_comment_result(issue_number, warning_message)
    if not post_result.ok:
        if post_result.failure_kind in {"unauthorized", "forbidden"}:
            raise RuntimeError(
                f"Permission denied posting overdue warning for #{issue_number} (status {post_result.status_code})."
            )
        if (
            post_result.failure_kind in {"invalid_payload", "server_error", "transport_error", "rate_limited"}
            or (post_result.status_code is not None and post_result.status_code < 400)
        ):
            existing_warning = _find_existing_warning_comment(
                bot,
                issue_number,
                reviewer,
                anchor_timestamp,
                current_scope_key=current_scope_key,
                current_scope_basis=current_scope_basis,
            )
            if existing_warning.get("status") == "found":
                review_data["transition_warning_sent"] = existing_warning.get("timestamp")
                _clear_transport_failure(bot, review_data, issue_number, phase="warning_post")
                bot.collect_touched_item(issue_number)
                return True
        changed = _record_transport_failure(bot, review_data, issue_number, phase="warning_post", result=post_result)
        return changed or changed

    changed = _clear_transport_failure(bot, review_data, issue_number, phase="warning_post") or changed

    now = bot.datetime.now(bot.timezone.utc).isoformat()
    review_data["transition_warning_sent"] = now
    bot.collect_touched_item(issue_number)

    _log(bot, "info", f"Posted overdue warning for #{issue_number} to @{reviewer}", issue_number=issue_number, reviewer=reviewer)
    return True
