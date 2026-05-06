"""Overdue review domain logic for reviewer-bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import assignment_flow
from .config import TRANSITION_NOTICE_MARKER_PREFIX, TRANSITION_WARNING_MARKER_PREFIX
from .reminder_comments import ReminderCommentScan, scan_reviewer_reminder_comments
from .repair_records import clear_repair_marker, store_repair_marker
from .timestamps import parse_iso8601_utc

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


def _scoped_delivery_receipt(
    *,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
    persisted_state: dict,
) -> ReminderScopeReceipt | None:
    sidecars = persisted_state.get("sidecars") if isinstance(persisted_state, dict) else None
    receipts = sidecars.get("reminder_delivery_receipts") if isinstance(sidecars, dict) else None
    if not isinstance(receipts, dict):
        return None
    candidates: list[tuple[str, ReminderScopeReceipt]] = []
    for row in receipts.values():
        if not isinstance(row, dict):
            continue
        row_scope = row.get("scope_key") if isinstance(row.get("scope_key"), str) else None
        if scope_key is not None and row_scope != scope_key:
            continue
        row_reviewer = row.get("reviewer") if isinstance(row.get("reviewer"), str) else None
        if reviewer and (not row_reviewer or row_reviewer.lower() != reviewer.lower()):
            continue
        row_head = row.get("head_sha") if isinstance(row.get("head_sha"), str) else None
        if head_sha and row_head != head_sha:
            continue
        row_cycle = row.get("cycle_key") if isinstance(row.get("cycle_key"), str) else None
        if cycle_key and row_cycle != cycle_key:
            continue
        kind = row.get("receipt_kind")
        created_at = row.get("comment_created_at")
        if kind not in {"warning", "transition"} or not isinstance(created_at, str) or not created_at.strip():
            continue
        receipt = ReminderScopeReceipt(
            issue_number,
            row_reviewer or reviewer,
            row_head or head_sha,
            row_cycle or cycle_key,
            row_scope or scope_key,
            str(kind),
            row.get("comment_id"),
            created_at,
            "state",
            "found",
            None,
        )
        candidates.append((created_at, receipt))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1]


def _same_login(left: str | None, right: str | None) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.strip() and left.lower() == right.lower()


def _marker_field(first_line: str, field_name: str) -> str | None:
    prefix = f"{field_name}="
    for part in first_line.replace("-->", "").split():
        if part.startswith(prefix):
            value = part[len(prefix) :].strip()
            return value or None
    return None


def _receipt_from_scanned_comments(
    *,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
    scanned_comments: tuple[object, ...],
) -> ReminderScopeReceipt | None:
    records = sorted(
        scanned_comments,
        key=lambda item: (getattr(item, "created_at", ""), str(getattr(item, "comment_id", "")), getattr(item, "matched_shape", "")),
    )
    legacy_records = []
    for record in records:
        shape = getattr(record, "matched_shape", "")
        first_line = getattr(record, "body_first_line", "")
        if shape in {"markerized_warning", "markerized_transition_notice"}:
            marker_issue = _marker_field(first_line, "issue")
            marker_reviewer = _marker_field(first_line, "reviewer")
            if marker_issue != str(issue_number) or not _same_login(marker_reviewer, reviewer):
                continue
            receipt_kind = "transition" if shape == "markerized_transition_notice" else "warning"
            return ReminderScopeReceipt(
                issue_number,
                reviewer,
                head_sha,
                cycle_key,
                scope_key,
                receipt_kind,
                getattr(record, "comment_id", None),
                getattr(record, "created_at", None),
                "comment_scan",
                "found",
                None,
            )
        if shape in {
            "legacy_unmarked_warning",
            "legacy_unmarked_transition_notice",
            "legacy_actions_warning_or_reminder",
        }:
            legacy_records.append(record)

    if len(legacy_records) >= 2:
        latest = legacy_records[-1]
        shape = getattr(latest, "matched_shape", "")
        receipt_kind = "legacy_transition" if "transition" in shape else "legacy_warning_or_reminder"
        return ReminderScopeReceipt(
            issue_number,
            reviewer,
            head_sha,
            cycle_key,
            scope_key,
            receipt_kind,
            getattr(latest, "comment_id", None),
            getattr(latest, "created_at", None),
            "legacy_duplicate_comment_scan",
            "found",
            None,
        )
    if legacy_records:
        latest = legacy_records[-1]
        return ReminderScopeReceipt(
            issue_number,
            reviewer,
            head_sha,
            cycle_key,
            scope_key,
            "none",
            getattr(latest, "comment_id", None),
            getattr(latest, "created_at", None),
            "blocked",
            "unavailable",
            "ambiguous_legacy_reminder_scan",
        )
    return None


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
    scoped_receipt = _scoped_delivery_receipt(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=head_sha,
        cycle_key=cycle_key,
        scope_key=scope_key,
        persisted_state=persisted_state,
    )
    if scoped_receipt is not None:
        return scoped_receipt
    scanned_receipt = _receipt_from_scanned_comments(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=head_sha,
        cycle_key=cycle_key,
        scope_key=scope_key,
        scanned_comments=scanned_comments,
    )
    if scanned_receipt is not None:
        return scanned_receipt
    warning = persisted_state.get("transition_warning_sent") if isinstance(persisted_state, dict) else None
    notice = persisted_state.get("transition_notice_sent_at") if isinstance(persisted_state, dict) else None
    if isinstance(warning, str) and warning.strip() and isinstance(notice, str) and notice.strip():
        return ReminderScopeReceipt(
            issue_number,
            reviewer,
            head_sha,
            cycle_key,
            scope_key,
            "legacy_transition",
            None,
            notice,
            "state",
            "found",
            "legacy_duplicate_exhausted",
        )
    if isinstance(notice, str) and notice.strip():
        return ReminderScopeReceipt(issue_number, reviewer, head_sha, cycle_key, scope_key, "none", None, notice, "blocked", "unavailable", "scope_unbound_legacy_field")
    if isinstance(warning, str) and warning.strip():
        return ReminderScopeReceipt(issue_number, reviewer, head_sha, cycle_key, scope_key, "none", None, warning, "blocked", "unavailable", "scope_unbound_legacy_field")
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
    elif comment_posted and not state_save_attempted:
        result = "blocked"
        diagnostic_reason = diagnostic_reason or "state_save_not_attempted_after_comment_post"
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


def _parse_reminder_timestamp(value: object) -> datetime | None:
    return parse_iso8601_utc(value)


def derive_reminder_cadence_decision(
    response,
    *,
    receipt: ReminderScopeReceipt | None,
    reminder_scan: ReminderCommentScan | None,
    now: object,
    review_deadline_days: int,
    transition_period_days: int,
) -> ReminderCadenceDecision:
    issue_number = int(getattr(response, "scope", None).issue_number or 0) if getattr(response, "scope", None) else 0
    reviewer = getattr(getattr(response, "scope", None), "reviewer", None)
    if receipt is not None and (receipt.source == "blocked" or receipt.status in {"unavailable", "malformed"}):
        return ReminderCadenceDecision(
            issue_number=int(getattr(response, "scope", None).issue_number or 0) if getattr(response, "scope", None) else 0,
            reviewer=getattr(getattr(response, "scope", None), "reviewer", None),
            scope=getattr(response, "scope", None),
            cadence_state="blocked",
            exhaustion_reason="blocked",
            warning_receipt=None,
            transition_receipt=None,
            legacy_duplicate_count=reminder_scan.baseline_count if reminder_scan is not None else 0,
            may_post_warning=False,
            may_post_transition=False,
            must_project_reassignment_needed=False,
        )
    effective_receipt = receipt if receipt is not None and receipt.receipt_kind != "none" else None
    legacy_duplicate_count = reminder_scan.baseline_count if reminder_scan is not None else 0
    exhausted = (effective_receipt is not None and effective_receipt.receipt_kind in {"transition", "legacy_transition"}) or legacy_duplicate_count >= 2
    now_dt = _parse_reminder_timestamp(now)
    anchor_dt = _parse_reminder_timestamp(getattr(response, "anchor_timestamp", None))
    receipt_dt = _parse_reminder_timestamp(effective_receipt.created_at if effective_receipt else None)
    cadence_state = "exhausted" if exhausted else "not_started"
    may_post_warning = False
    may_post_transition = False
    if not exhausted and getattr(response, "response_state", None) == "awaiting_reviewer_response":
        if effective_receipt is not None and effective_receipt.receipt_kind in {"warning", "legacy_warning_or_reminder"}:
            if now_dt is not None and receipt_dt is not None and (now_dt - receipt_dt).days >= transition_period_days:
                cadence_state = "transition_due"
                may_post_transition = True
        elif effective_receipt is None and now_dt is not None and anchor_dt is not None and (now_dt - anchor_dt).days >= review_deadline_days:
            cadence_state = "warning_due"
            may_post_warning = True
        elif now_dt is None or (effective_receipt is None and anchor_dt is None):
            cadence_state = "blocked"
    return ReminderCadenceDecision(
        issue_number=issue_number,
        reviewer=reviewer,
        scope=getattr(response, "scope", None),
        cadence_state=cadence_state,
        exhaustion_reason="legacy_duplicate_reminders_exhausted" if legacy_duplicate_count >= 2 else "transition_notice_sent" if exhausted else "not_exhausted",
        warning_receipt=effective_receipt if effective_receipt and effective_receipt.receipt_kind in {"warning", "legacy_warning_or_reminder"} else None,
        transition_receipt=effective_receipt if effective_receipt and effective_receipt.receipt_kind in {"transition", "legacy_transition"} else None,
        legacy_duplicate_count=legacy_duplicate_count,
        may_post_warning=may_post_warning,
        may_post_transition=may_post_transition,
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
    elif cadence.cadence_state == "transition_due" and cadence.may_post_transition:
        action = "transition"
        reason = "transition_due"
    elif cadence.cadence_state == "warning_due" and cadence.may_post_warning:
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
        earliest = _parse_reminder_timestamp(not_before)
    page = 1
    while True:
        try:
            response = bot.github.list_issue_comments_result(issue_number, page=page)
        except (AssertionError, RuntimeError):
            return {"status": "missing"}
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
            created_dt = _parse_reminder_timestamp(created_at)
            if created_dt is None:
                continue
            if earliest is not None and created_dt < earliest:
                continue
            lines = body.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line == marker:
                if first_match is None or created_dt < first_match[0]:
                    first_match = (created_dt, created_at, comment.get("id"))
        if first_match is not None:
            return {"status": "found", "timestamp": first_match[1], "comment_id": first_match[2]}
        if len(response.payload) < 100:
            break
        page += 1
    return {"status": "missing"}


def _warning_scan_result(bot, issue_number: int, reviewer: str, anchor_timestamp: str | None) -> dict[str, object]:
    return _find_existing_warning_comment(bot, issue_number, reviewer, anchor_timestamp)


def _warning_receipt_from_result(
    *,
    issue_number: int,
    reviewer: str | None,
    head_sha: str | None,
    cycle_key: str | None,
    scope_key: str | None,
    result: dict[str, object],
    source: str,
) -> ReminderScopeReceipt | None:
    timestamp = result.get("timestamp") or result.get("created_at")
    if result.get("status") not in {"found", "posted"} or not isinstance(timestamp, str) or not timestamp.strip():
        return None
    return ReminderScopeReceipt(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=head_sha,
        cycle_key=cycle_key,
        scope_key=scope_key,
        receipt_kind="warning",
        comment_id=result.get("comment_id"),
        created_at=timestamp,
        source=source,
        status="found",
        reason=None,
    )


def _store_reminder_delivery_result(review_data: dict, result: ReminderDeliveryPersistenceResult) -> bool:
    sidecars = review_data.setdefault("sidecars", {})
    if not isinstance(sidecars, dict):
        sidecars = {}
        review_data["sidecars"] = sidecars
    receipts = sidecars.setdefault("reminder_delivery_receipts", {})
    if not isinstance(receipts, dict):
        receipts = {}
        sidecars["reminder_delivery_receipts"] = receipts
    key = f"{result.receipt_kind}:{result.scope_key or result.issue_number}:{result.comment_id or result.comment_created_at or 'pending'}"
    row = result.to_output()
    previous = receipts.get(key)
    receipts[key] = row
    return previous != row


def _scan_live_reminder_comments(bot, issue_number: int) -> ReminderCommentScan | None:
    try:
        response = bot.github.list_issue_comments_result(issue_number, page=1)
    except (AssertionError, AttributeError, RuntimeError):
        return None
    if not response.ok or not isinstance(response.payload, list):
        return None
    return scan_reviewer_reminder_comments(response.payload)


def _effective_response_with_cadence(bot, issue_number: int, review_data: dict, response_state: dict) -> tuple[object, ReminderCadenceDecision, object]:
    from scripts.reviewer_bot_core import reviewer_response_policy

    response_payload = dict(response_state)
    response_payload.setdefault("issue_number", issue_number)
    response_payload.setdefault("current_reviewer", review_data.get("current_reviewer"))
    response = reviewer_response_policy.to_reviewer_response_decision(response_payload)
    reminder_scan = _scan_live_reminder_comments(bot, issue_number)
    receipt = derive_reminder_scope_receipt(
        issue_number=issue_number,
        reviewer=getattr(response.scope, "reviewer", None) if response.scope else review_data.get("current_reviewer"),
        head_sha=getattr(response.scope, "head_sha", None) if response.scope else None,
        cycle_key=getattr(response.scope, "cycle_key", None) if response.scope else None,
        scope_key=getattr(response.scope, "scope_key", None) if response.scope else None,
        persisted_state=review_data,
        scanned_comments=reminder_scan.records if reminder_scan is not None else (),
    )
    cadence = derive_reminder_cadence_decision(
        response,
        receipt=receipt,
        reminder_scan=reminder_scan,
        now=bot.datetime.now(bot.timezone.utc),
        review_deadline_days=bot.REVIEW_DEADLINE_DAYS,
        transition_period_days=bot.TRANSITION_PERIOD_DAYS,
    )
    effective_response = reviewer_response_policy.apply_reminder_cadence_overlay(response, cadence)
    return effective_response, cadence, reminder_scan


def backfill_transition_warning_if_present(bot, state: dict, issue_number: int) -> bool:
    active_reviews = state.get("active_reviews") if isinstance(state, dict) else None
    review_data = active_reviews.get(str(issue_number)) if isinstance(active_reviews, dict) else None
    if not isinstance(review_data, dict):
        return False
    if not isinstance(review_data.get("current_reviewer"), str) or not review_data["current_reviewer"].strip():
        return False
    existing_warning = review_data.get("transition_warning_sent")
    if isinstance(existing_warning, str) and existing_warning.strip():
        return False
    try:
        issue_snapshot_result = bot.github.get_issue_or_pr_snapshot_result(issue_number)
    except (AssertionError, AttributeError, RuntimeError):
        return False
    issue_snapshot = issue_snapshot_result.payload if issue_snapshot_result.ok else None
    if not isinstance(issue_snapshot, dict):
        return False
    if str(issue_snapshot.get("state", "")).lower() == "closed":
        return False

    response_state = bot.adapters.review_state.compute_reviewer_response_state(
        issue_number,
        review_data,
        issue_snapshot=issue_snapshot,
    )
    _effective_response, cadence, _reminder_scan = _effective_response_with_cadence(
        bot,
        issue_number,
        review_data,
        response_state,
    )
    receipt = cadence.warning_receipt
    if receipt is None or receipt.receipt_kind != "warning":
        return False
    if receipt.source not in {"comment_scan", "live_comment_scan"}:
        return False
    if not isinstance(receipt.created_at, str) or not receipt.created_at.strip():
        return False

    changed = False
    if review_data.get("transition_warning_sent") != receipt.created_at:
        review_data["transition_warning_sent"] = receipt.created_at
        changed = True
    delivery_result = build_reminder_delivery_persistence_result(
        issue_number=issue_number,
        reviewer=receipt.reviewer,
        head_sha=receipt.head_sha,
        cycle_key=receipt.cycle_key,
        scope_key=receipt.scope_key,
        receipt_kind="warning",
        comment_posted=False,
        comment_id=receipt.comment_id,
        comment_created_at=receipt.created_at,
        state_save_attempted=False,
        state_save_succeeded=False,
        recovered_receipt=receipt,
        diagnostic_reason="live_warning_receipt_backfill",
    )
    changed = _store_reminder_delivery_result(review_data, delivery_result) or changed
    if changed:
        bot.collect_touched_item(issue_number)
    return changed


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
        try:
            response = bot.github.list_issue_comments_result(issue_number, page=page)
        except (AssertionError, RuntimeError):
            return {"status": "missing"}
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
            created_dt = _parse_reminder_timestamp(created_at)
            if created_dt is None:
                continue
            if first_match is None or created_dt < first_match[0]:
                first_match = (created_dt, created_at, comment.get("id"))
        if first_match is not None:
            return {"status": "found", "timestamp": first_match[1], "comment_id": first_match[2]}
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
    effective_response, cadence, _reminder_scan = _effective_response_with_cadence(bot, issue_number, review_data, response_state)
    response_name = effective_response.response_state
    current_scope_key = effective_response.scope.scope_key if effective_response.scope else None
    current_scope_basis = effective_response.scope.scope_basis if effective_response.scope else None
    suppression_reason = effective_response.suppression_reason
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
    reminder_decision = decide_overdue_reminder(
        effective_response,
        cadence=cadence,
        now=bot.datetime.now(bot.timezone.utc),
        review_deadline_days=bot.REVIEW_DEADLINE_DAYS,
        transition_period_days=bot.TRANSITION_PERIOD_DAYS,
    )
    preview["would_post_warning"] = reminder_decision.action == "warning"
    preview["would_post_transition"] = reminder_decision.action == "transition"
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
        effective_response, cadence, _reminder_scan = _effective_response_with_cadence(bot, issue_number, review_data, response_state)
        reminder_decision = decide_overdue_reminder(
            effective_response,
            cadence=cadence,
            now=now,
            review_deadline_days=bot.REVIEW_DEADLINE_DAYS,
            transition_period_days=bot.TRANSITION_PERIOD_DAYS,
        )
        if reminder_decision.action == "none":
            continue
        response_name = effective_response.response_state
        if response_name != "awaiting_reviewer_response":
            continue
        last_activity = effective_response.anchor_timestamp
        anchor_reason = effective_response.reason
        current_scope_key = effective_response.scope.scope_key if effective_response.scope else None
        current_scope_basis = effective_response.scope.scope_basis if effective_response.scope else None

        if not last_activity:
            continue

        last_activity_dt = _parse_reminder_timestamp(last_activity)
        if last_activity_dt is None:
            continue

        days_since_activity = (now - last_activity_dt).days

        if days_since_activity < bot.REVIEW_DEADLINE_DAYS:
            continue

        if reminder_decision.action == "transition":
            warning_dt = _parse_reminder_timestamp(
                reminder_decision.receipt.created_at if reminder_decision.receipt is not None else None
            )
            if warning_dt is None:
                continue
            overdue.append(
                {
                    "issue_number": issue_number,
                    "reviewer": current_reviewer,
                    "days_overdue": days_since_activity,
                    "days_since_warning": (now - warning_dt).days,
                    "needs_warning": False,
                    "needs_transition": True,
                    "anchor_reason": anchor_reason,
                    "anchor_timestamp": last_activity,
                    "current_scope_key": current_scope_key,
                    "current_scope_basis": current_scope_basis,
                }
            )
        elif reminder_decision.action == "warning":
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
        receipt = _warning_receipt_from_result(
            issue_number=issue_number,
            reviewer=reviewer,
            head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
            cycle_key=review_data.get("cycle_key") if isinstance(review_data.get("cycle_key"), str) else None,
            scope_key=current_scope_key,
            result=existing_warning,
            source="live_comment_scan",
        )
        if receipt is None:
            return changed
        review_data["transition_warning_sent"] = receipt.created_at
        delivery_result = build_reminder_delivery_persistence_result(
            issue_number=issue_number,
            reviewer=reviewer,
            head_sha=receipt.head_sha,
            cycle_key=receipt.cycle_key,
            scope_key=receipt.scope_key,
            receipt_kind="warning",
            comment_posted=False,
            comment_id=receipt.comment_id,
            comment_created_at=receipt.created_at,
            state_save_attempted=False,
            state_save_succeeded=False,
            recovered_receipt=receipt,
        )
        changed = _store_reminder_delivery_result(review_data, delivery_result) or changed
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
                receipt = _warning_receipt_from_result(
                    issue_number=issue_number,
                    reviewer=reviewer,
                    head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
                    cycle_key=review_data.get("cycle_key") if isinstance(review_data.get("cycle_key"), str) else None,
                    scope_key=current_scope_key,
                    result=existing_warning,
                    source="live_comment_scan_after_post_failure",
                )
                if receipt is None:
                    changed = _record_transport_failure(bot, review_data, issue_number, phase="warning_post", result=post_result)
                    return changed or changed
                review_data["transition_warning_sent"] = receipt.created_at
                delivery_result = build_reminder_delivery_persistence_result(
                    issue_number=issue_number,
                    reviewer=reviewer,
                    head_sha=receipt.head_sha,
                    cycle_key=receipt.cycle_key,
                    scope_key=receipt.scope_key,
                    receipt_kind="warning",
                    comment_posted=True,
                    comment_id=receipt.comment_id,
                    comment_created_at=receipt.created_at,
                    state_save_attempted=True,
                    state_save_succeeded=False,
                    recovered_receipt=receipt,
                    diagnostic_reason=post_result.failure_kind,
                )
                changed = _store_reminder_delivery_result(review_data, delivery_result) or changed
                _clear_transport_failure(bot, review_data, issue_number, phase="warning_post")
                bot.collect_touched_item(issue_number)
                return True
        changed = _record_transport_failure(bot, review_data, issue_number, phase="warning_post", result=post_result)
        return changed or changed

    changed = _clear_transport_failure(bot, review_data, issue_number, phase="warning_post") or changed

    posted_payload = post_result.payload if isinstance(post_result.payload, dict) else {}
    posted_result = {
        "status": "posted",
        "timestamp": posted_payload.get("created_at"),
        "created_at": posted_payload.get("created_at"),
        "comment_id": posted_payload.get("id"),
    }
    receipt = _warning_receipt_from_result(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
        cycle_key=review_data.get("cycle_key") if isinstance(review_data.get("cycle_key"), str) else None,
        scope_key=current_scope_key,
        result=posted_result,
        source="post_comment_response",
    )
    if receipt is None:
        rescanned_warning = _find_existing_warning_comment(
            bot,
            issue_number,
            reviewer,
            anchor_timestamp,
            current_scope_key=current_scope_key,
            current_scope_basis=current_scope_basis,
        )
        receipt = _warning_receipt_from_result(
            issue_number=issue_number,
            reviewer=reviewer,
            head_sha=review_data.get("active_head_sha") if isinstance(review_data.get("active_head_sha"), str) else None,
            cycle_key=review_data.get("cycle_key") if isinstance(review_data.get("cycle_key"), str) else None,
            scope_key=current_scope_key,
            result=rescanned_warning,
            source="live_comment_scan_after_post_success",
        )
    if receipt is not None:
        review_data["transition_warning_sent"] = receipt.created_at
    delivery_result = build_reminder_delivery_persistence_result(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=receipt.head_sha if receipt is not None else None,
        cycle_key=receipt.cycle_key if receipt is not None else None,
        scope_key=current_scope_key,
        receipt_kind="warning",
        comment_posted=True,
        comment_id=receipt.comment_id if receipt is not None else None,
        comment_created_at=receipt.created_at if receipt is not None else None,
        state_save_attempted=False,
        state_save_succeeded=False,
        recovered_receipt=receipt,
        diagnostic_reason=None if receipt is not None else "posted_comment_missing_created_at_receipt",
    )
    changed = _store_reminder_delivery_result(review_data, delivery_result) or changed
    bot.collect_touched_item(issue_number)

    _log(bot, "info", f"Posted overdue warning for #{issue_number} to @{reviewer}", issue_number=issue_number, reviewer=reviewer)
    return True
