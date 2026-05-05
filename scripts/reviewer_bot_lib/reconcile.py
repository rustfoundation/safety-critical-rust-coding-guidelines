"""Trusted deferred reconcile helpers for reviewer-bot workflow_run processing."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from scripts.reviewer_bot_core import comment_routing_policy, reconcile_replay_policy
from scripts.reviewer_bot_core.comment_routing_policy import (
    ObserverCommentClassification,
)

from . import assignment_flow
from . import deferred_gap_bookkeeping as gap_bookkeeping
from . import reconcile_payloads as _reconcile_payloads
from .comment_application import (
    digest_comment_body,
    process_comment_event,
    record_conversation_freshness,
)
from .comment_routing import classify_comment_payload, classify_issue_comment_actor
from .context import CommentEventRequest
from .event_inputs import (
    InvalidEventInput,
    build_event_context,
    build_replay_comment_event_request,
)
from .reconcile_payloads import (
    DeferredArtifactSourceAuthority,
    DeferredCommentPayload,
    DeferredCommentReplayContext,
    DeferredReviewPayload,
    build_deferred_comment_replay_context,
    build_deferred_review_replay_context,
    deferred_workflow_source_contract_for_payload_kind,
    derive_deferred_artifact_source_authority,
    parse_deferred_context_payload,
)
from .reconcile_reads import (
    LiveCommentReplayContext,
    ReconcileReadError,
)
from .reconcile_reads import (
    read_live_comment_replay_context as _read_live_comment_replay_context,
)
from .reconcile_reads import (
    read_live_pr_replay_context as _read_live_pr_replay_context,
)
from .reconcile_reads import (
    read_optional_reconcile_object as _read_optional_reconcile_object,
)
from .reconcile_reads import (
    read_reconcile_object as _read_reconcile_object,
)
from .reconcile_reads import (
    read_reconcile_reviews as _read_reconcile_reviews,
)
from .reconcile_reads import (
    resolve_review_dismissal_time as _resolve_review_dismissal_time,
)
from .review_state import (
    accept_channel_event,
    ensure_review_entry,
    record_reviewer_activity,
    refresh_reviewer_review_from_live_preferred_review,
    set_current_reviewer,
)
from .reviews import rebuild_pr_approval_state_result
from .runtime_protocols import (
    ReconcileRectifyRuntimeContext,
    ReconcileWorkflowRuntimeContext,
)

DeferredArtifactIdentity = _reconcile_payloads.DeferredArtifactIdentity
DeferredReviewReplayContext = _reconcile_payloads.DeferredReviewReplayContext
ParsedWorkflowRunPayload = DeferredReviewPayload | DeferredCommentPayload


@dataclass(frozen=True)
class WorkflowRunHandlerResult:
    state_changed: bool
    touched_items: list[int]


@dataclass(frozen=True)
class LiveReviewObservation:
    review_id: int | str
    live_found: bool
    read_status: str
    visibility_status: str
    commit_id: str | None
    submitted_at: str | None
    state: str | None
    author: str | None
    failure_kind: str | None
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "live_found": self.live_found,
            "read_status": self.read_status,
            "visibility_status": self.visibility_status,
            "commit_id": self.commit_id,
            "submitted_at": self.submitted_at,
            "state": self.state,
            "author": self.author,
            "failure_kind": self.failure_kind,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class WorkflowRunReplayAdmission:
    source_event_key: str | None
    triggering_conclusion: str | None
    payload_kind: str | None
    admission_state: str
    replay_allowed: bool
    diagnostic_allowed: bool
    mark_reconciled_allowed: bool
    clear_gap_allowed: bool
    reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "source_event_key": self.source_event_key,
            "triggering_conclusion": self.triggering_conclusion,
            "payload_kind": self.payload_kind,
            "admission_state": self.admission_state,
            "replay_allowed": self.replay_allowed,
            "diagnostic_allowed": self.diagnostic_allowed,
            "mark_reconciled_allowed": self.mark_reconciled_allowed,
            "clear_gap_allowed": self.clear_gap_allowed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReviewReplayDecisionInput:
    pr_number: int
    review_id: int
    source_event_key: str
    actor_login: str | None
    current_reviewer: str | None
    live_observation: LiveReviewObservation
    current_head_sha: str | None
    admission: WorkflowRunReplayAdmission


@dataclass(frozen=True)
class OpenItemReconcileRecoveryContext:
    pr_number: int
    source_event_key: str
    source_event_name: str
    source_event_action: str
    live_pr_state: str | None
    live_head_sha: str | None
    live_author: str | None
    live_labels: tuple[str, ...]
    recovered_current_reviewer: str | None
    recovery_status: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "pr_number": self.pr_number,
            "source_event_key": self.source_event_key,
            "source_event_name": self.source_event_name,
            "source_event_action": self.source_event_action,
            "live_pr_state": self.live_pr_state,
            "live_head_sha": self.live_head_sha,
            "live_author": self.live_author,
            "live_labels": sorted(self.live_labels),
            "recovered_current_reviewer": self.recovered_current_reviewer,
            "recovery_status": self.recovery_status,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class CommandReplayReceipt:
    source_event_key: str
    issue_number: int | None
    command_name: str | None
    replay_attempted: bool
    command_side_effects_attempted: tuple[str, ...]
    state_save_required: bool
    state_save_succeeded: bool
    mark_reconciled_allowed: bool
    clear_gap_allowed: bool
    result: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "source_event_key": self.source_event_key,
            "issue_number": self.issue_number,
            "command_name": self.command_name,
            "replay_attempted": self.replay_attempted,
            "command_side_effects_attempted": sorted(self.command_side_effects_attempted),
            "state_save_required": self.state_save_required,
            "state_save_succeeded": self.state_save_succeeded,
            "mark_reconciled_allowed": self.mark_reconciled_allowed,
            "clear_gap_allowed": self.clear_gap_allowed,
            "result": self.result,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class ReconcileTarget:
    pr_number: int
    source_event_key: str
    payload_kind: str | None
    parsed_payload: object | None
    recovered_identity: object | None
    live_pr_state: str | None
    admission: WorkflowRunReplayAdmission


def build_workflow_run_replay_admission(
    *,
    source_event_key: str | None,
    triggering_conclusion: str | None,
    payload_kind: str | None,
    source_authority_status: str | None,
    payload_valid: bool,
    identity_present: bool,
) -> WorkflowRunReplayAdmission:
    if triggering_conclusion and triggering_conclusion != "success":
        return WorkflowRunReplayAdmission(source_event_key, triggering_conclusion, payload_kind, "non_success_diagnostic_only", False, True, False, False, f"observer_{triggering_conclusion}")
    if not identity_present:
        return WorkflowRunReplayAdmission(source_event_key, triggering_conclusion, payload_kind, "blocked_missing_identity", False, True, False, False, "missing_identity")
    if not payload_valid:
        return WorkflowRunReplayAdmission(source_event_key, triggering_conclusion, payload_kind, "blocked_payload_invalid", False, True, False, False, "payload_invalid")
    if source_authority_status not in {"trusted_exact_identity", None}:
        return WorkflowRunReplayAdmission(source_event_key, triggering_conclusion, payload_kind, "blocked_untrusted_source", False, True, False, False, source_authority_status)
    return WorkflowRunReplayAdmission(source_event_key, triggering_conclusion, payload_kind, "trusted_success_replay_allowed", True, True, True, True, None)


def build_command_replay_receipt(
    *,
    source_event_key: str,
    issue_number: int | None,
    command_name: str | None,
    replay_attempted: bool,
    command_side_effects_attempted: tuple[str, ...],
    state_save_required: bool,
    state_save_succeeded: bool,
    mark_reconciled_allowed: bool,
    clear_gap_allowed: bool,
    diagnostic_reason: str | None = None,
) -> CommandReplayReceipt:
    if not replay_attempted:
        result = "pass_diagnostic_only"
    elif not mark_reconciled_allowed or not clear_gap_allowed:
        result = "blocked_authority_missing"
    elif state_save_required and not state_save_succeeded:
        result = "blocked_state_save_failed"
    else:
        result = "pass_replayed_and_persisted"
    return CommandReplayReceipt(
        source_event_key=source_event_key,
        issue_number=issue_number,
        command_name=command_name,
        replay_attempted=replay_attempted,
        command_side_effects_attempted=command_side_effects_attempted,
        state_save_required=state_save_required,
        state_save_succeeded=state_save_succeeded,
        mark_reconciled_allowed=mark_reconciled_allowed,
        clear_gap_allowed=clear_gap_allowed,
        result=result,
        diagnostic_reason=diagnostic_reason,
    )


def decide_review_submitted_replay_from_input(inputs: ReviewReplayDecisionInput):
    return reconcile_replay_policy.decide_review_submitted_replay(
        source_event_key=inputs.source_event_key,
        actor_login=inputs.actor_login,
        current_reviewer=inputs.current_reviewer,
        live_commit_id=inputs.live_observation.commit_id if inputs.admission.replay_allowed else None,
        live_submitted_at=inputs.live_observation.submitted_at if inputs.admission.replay_allowed else None,
    )


def apply_reconcile_command_with_receipt(bot, state: dict, target: ReconcileTarget) -> CommandReplayReceipt:
    del bot, state
    command_metadata = target.parsed_payload if isinstance(target.parsed_payload, dict) else {}
    replay_attempted = bool(command_metadata.get("replay_attempted"))
    mark_reconciled_requested = bool(command_metadata.get("mark_reconciled_requested"))
    clear_gap_requested = bool(command_metadata.get("clear_gap_requested"))
    return build_command_replay_receipt(
        source_event_key=target.source_event_key,
        issue_number=target.pr_number,
        command_name=command_metadata.get("command_name") if isinstance(command_metadata.get("command_name"), str) else None,
        replay_attempted=replay_attempted,
        command_side_effects_attempted=tuple(
            str(item) for item in command_metadata.get("command_side_effects_attempted", ())
        ),
        state_save_required=bool(command_metadata.get("state_save_required")),
        state_save_succeeded=bool(command_metadata.get("state_save_succeeded")),
        mark_reconciled_allowed=bool(mark_reconciled_requested and target.admission.mark_reconciled_allowed),
        clear_gap_allowed=bool(clear_gap_requested and target.admission.clear_gap_allowed),
        diagnostic_reason=target.admission.reason or command_metadata.get("diagnostic_reason"),
    )


def _store_command_replay_receipt(review_data: dict, receipt: CommandReplayReceipt) -> bool:
    receipts = review_data.setdefault("sidecars", {}).setdefault("command_replay_receipts", {})
    if not isinstance(receipts, dict):
        receipts = {}
        review_data.setdefault("sidecars", {})["command_replay_receipts"] = receipts
    row = receipt.to_output()
    previous = receipts.get(receipt.source_event_key)
    receipts[receipt.source_event_key] = row
    return previous != row


def _persisted_command_replay_receipt(
    review_data: dict,
    source_event_key: str,
    *,
    admission: WorkflowRunReplayAdmission,
) -> CommandReplayReceipt | None:
    receipts = review_data.get("sidecars", {}).get("command_replay_receipts") if isinstance(review_data.get("sidecars"), dict) else None
    row = receipts.get(source_event_key) if isinstance(receipts, dict) else None
    if not isinstance(row, dict) or not row.get("replay_attempted"):
        return None
    if not row.get("state_save_required"):
        return None
    if row.get("result") not in {"blocked_state_save_failed", "pass_replayed_and_persisted"}:
        return None
    side_effects = tuple(str(item) for item in row.get("command_side_effects_attempted", ()))
    return build_command_replay_receipt(
        source_event_key=source_event_key,
        issue_number=row.get("issue_number") if isinstance(row.get("issue_number"), int) else None,
        command_name=row.get("command_name") if isinstance(row.get("command_name"), str) else None,
        replay_attempted=True,
        command_side_effects_attempted=side_effects,
        state_save_required=True,
        state_save_succeeded=True,
        mark_reconciled_allowed=bool(row.get("mark_reconciled_allowed") and admission.mark_reconciled_allowed),
        clear_gap_allowed=bool(row.get("clear_gap_allowed") and admission.clear_gap_allowed),
        diagnostic_reason="persisted_command_replay_receipt_recovered",
    )


def _derive_parsed_payload_authority(
    parsed_payload: ParsedWorkflowRunPayload,
    *,
    triggering_conclusion: str | None,
) -> DeferredArtifactSourceAuthority:
    payload_kind = parsed_payload.identity.payload_kind.value
    contract = deferred_workflow_source_contract_for_payload_kind(payload_kind)
    return derive_deferred_artifact_source_authority(
        parsed_payload.identity,
        parsed_payload.raw_payload,
        triggering_conclusion=triggering_conclusion,
        contract=contract,
    )


def _admission_for_parsed_payload(
    parsed_payload: ParsedWorkflowRunPayload,
    *,
    triggering_conclusion: str | None,
) -> tuple[DeferredArtifactSourceAuthority, WorkflowRunReplayAdmission]:
    authority = _derive_parsed_payload_authority(
        parsed_payload,
        triggering_conclusion=triggering_conclusion,
    )
    admission = build_workflow_run_replay_admission(
        source_event_key=parsed_payload.identity.source_event_key,
        triggering_conclusion=triggering_conclusion,
        payload_kind=parsed_payload.identity.payload_kind.value,
        source_authority_status=authority.authority_status,
        payload_valid=authority.authority_status not in {"blocked_source_mismatch", "blocked_action_mismatch"},
        identity_present=authority.authority_status != "blocked_missing_identity",
    )
    return authority, admission


def _record_blocked_admission_gap(
    bot: ReconcileWorkflowRuntimeContext,
    review_data: dict,
    parsed_payload: ParsedWorkflowRunPayload,
    authority: DeferredArtifactSourceAuthority,
    admission: WorkflowRunReplayAdmission,
) -> bool:
    payload = parsed_payload.raw_payload
    return gap_bookkeeping.record_deferred_gap_diagnostic(
        bot,
        review_data,
        payload,
        "artifact_invalid" if admission.admission_state != "non_success_diagnostic_only" else "observer_failed",
        (
            "Deferred observer source authority did not permit replay; "
            f"authority={authority.authority_status}; admission={admission.admission_state}; "
            f"reason={authority.diagnostic_reason or admission.reason or 'unavailable'}. "
            f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
        ),
        failure_kind=admission.admission_state,
    )


def _log(bot: ReconcileWorkflowRuntimeContext, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _read_live_pr_state_for_reconcile(bot: ReconcileWorkflowRuntimeContext, pr_number: int) -> str:
    live_pr = _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number}")
    live_state = live_pr.get("state")
    if not isinstance(live_state, str) or not live_state.strip():
        raise ReconcileReadError(f"live PR #{pr_number} state is invalid", failure_kind="invalid_payload")
    return live_state.strip().lower()


def _login_values(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    logins: list[str] = []
    for value in values:
        login = value.get("login") if isinstance(value, dict) else value
        if isinstance(login, str) and login.strip():
            logins.append(login.strip())
    return tuple(logins)


def _live_pr_recovery_context(
    pr_number: int,
    source_event_key: str,
    source_event_name: str,
    source_event_action: str,
    live_pr: dict,
    *,
    recovered_current_reviewer: str | None,
    recovery_status: str,
    diagnostic_reason: str | None,
) -> OpenItemReconcileRecoveryContext:
    head = live_pr.get("head") if isinstance(live_pr.get("head"), dict) else {}
    author = live_pr.get("user") if isinstance(live_pr.get("user"), dict) else {}
    labels = tuple(
        str(label.get("name"))
        for label in live_pr.get("labels", [])
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    )
    return OpenItemReconcileRecoveryContext(
        pr_number=pr_number,
        source_event_key=source_event_key,
        source_event_name=source_event_name,
        source_event_action=source_event_action,
        live_pr_state=str(live_pr.get("state")) if isinstance(live_pr.get("state"), str) else None,
        live_head_sha=head.get("sha") if isinstance(head.get("sha"), str) else None,
        live_author=author.get("login") if isinstance(author.get("login"), str) else None,
        live_labels=labels,
        recovered_current_reviewer=recovered_current_reviewer,
        recovery_status=recovery_status,
        diagnostic_reason=diagnostic_reason,
    )


def _record_missing_row_orphan(state: dict, context: OpenItemReconcileRecoveryContext) -> bool:
    sidecars = state.setdefault("sidecars", {})
    if not isinstance(sidecars, dict):
        sidecars = {}
        state["sidecars"] = sidecars
    orphans = sidecars.setdefault("orphaned_deferred_reconcile_events", {})
    if not isinstance(orphans, dict):
        orphans = {}
        sidecars["orphaned_deferred_reconcile_events"] = orphans
    previous = orphans.get(context.source_event_key)
    row = context.to_output()
    orphans[context.source_event_key] = row
    return previous != row


def _recover_missing_active_review_entry(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    *,
    pr_number: int,
    source_event_key: str,
    source_event_name: str,
    source_event_action: str,
    allow_reconstruction: bool = True,
) -> tuple[dict | None, bool]:
    try:
        live_pr = _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number}")
    except (AssertionError, RuntimeError) as exc:
        context = OpenItemReconcileRecoveryContext(
            pr_number=pr_number,
            source_event_key=source_event_key,
            source_event_name=source_event_name,
            source_event_action=source_event_action,
            live_pr_state=None,
            live_head_sha=None,
            live_author=None,
            live_labels=(),
            recovered_current_reviewer=None,
            recovery_status="orphaned_deferred_event",
            diagnostic_reason=str(exc),
        )
        changed = _record_missing_row_orphan(state, context)
        if changed:
            bot.collect_touched_item(pr_number)
        return None, changed

    state_value = str(live_pr.get("state") or "").lower()
    if state_value == "closed":
        return None, False
    if not allow_reconstruction:
        context = _live_pr_recovery_context(
            pr_number,
            source_event_key,
            source_event_name,
            source_event_action,
            live_pr,
            recovered_current_reviewer=None,
            recovery_status="orphaned_deferred_event",
            diagnostic_reason="reconstruction_not_allowed_for_diagnostic_admission",
        )
        changed = _record_missing_row_orphan(state, context)
        if changed:
            bot.collect_touched_item(pr_number)
        return None, changed
    if state_value != "open":
        context = _live_pr_recovery_context(
            pr_number,
            source_event_key,
            source_event_name,
            source_event_action,
            live_pr,
            recovered_current_reviewer=None,
            recovery_status="orphaned_deferred_event",
            diagnostic_reason="live_pr_state_not_open",
        )
        changed = _record_missing_row_orphan(state, context)
        if changed:
            bot.collect_touched_item(pr_number)
        return None, changed

    author = live_pr.get("user") if isinstance(live_pr.get("user"), dict) else {}
    author_login = author.get("login") if isinstance(author.get("login"), str) else None
    candidate_logins = {
        login.lower(): login
        for login in (*_login_values(live_pr.get("requested_reviewers")), *_login_values(live_pr.get("assignees")))
        if not (isinstance(author_login, str) and login.lower() == author_login.lower())
    }
    if len(candidate_logins) != 1:
        context = _live_pr_recovery_context(
            pr_number,
            source_event_key,
            source_event_name,
            source_event_action,
            live_pr,
            recovered_current_reviewer=None,
            recovery_status="orphaned_deferred_event",
            diagnostic_reason="missing_row_recovery_requires_exactly_one_live_reviewer",
        )
        changed = _record_missing_row_orphan(state, context)
        if changed:
            bot.collect_touched_item(pr_number)
        return None, changed

    reviewer = next(iter(candidate_logins.values()))
    set_current_reviewer(
        state,
        pr_number,
        reviewer,
        assignment_method="deferred_reconcile_recovery",
        at=_now_iso(bot),
    )
    review_data = ensure_review_entry(state, pr_number, create=True)
    if review_data is None:
        return None, False
    head = live_pr.get("head") if isinstance(live_pr.get("head"), dict) else {}
    if isinstance(head.get("sha"), str) and head.get("sha"):
        review_data["active_head_sha"] = head["sha"]
    context = _live_pr_recovery_context(
        pr_number,
        source_event_key,
        source_event_name,
        source_event_action,
        live_pr,
        recovered_current_reviewer=reviewer,
        recovery_status="recovered_minimal_context",
        diagnostic_reason=None,
    )
    recoveries = review_data.setdefault("sidecars", {}).setdefault("open_item_reconcile_recoveries", {})
    recoveries[source_event_key] = context.to_output()
    bot.collect_touched_item(pr_number)
    return review_data, True


def _now_iso(bot: ReconcileWorkflowRuntimeContext) -> str:
    return bot.clock.now().isoformat()


def _record_review_rebuild(bot: ReconcileRectifyRuntimeContext, state: dict, issue_number: int, review_data: dict) -> bool:
    pull_request = _read_reconcile_object(bot, f"pulls/{issue_number}", label=f"pull request #{issue_number}")
    reviews = _read_reconcile_reviews(bot, issue_number)
    before = {
        "reviewer_review": deepcopy(review_data.get("reviewer_review")),
        "active_head_sha": review_data.get("active_head_sha"),
        "current_cycle_completion": deepcopy(review_data.get("current_cycle_completion")),
        "current_cycle_write_approval": deepcopy(review_data.get("current_cycle_write_approval")),
        "review_completed_at": review_data.get("review_completed_at"),
        "review_completed_by": review_data.get("review_completed_by"),
        "review_completion_source": review_data.get("review_completion_source"),
    }
    refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
        actor=review_data.get("current_reviewer"),
    )
    approval_result = rebuild_pr_approval_state_result(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if not approval_result.get("ok"):
        raise ReconcileReadError(
            f"Unable to rebuild approval state for PR #{issue_number}: {approval_result.get('reason')}",
            failure_kind=str(approval_result.get("failure_kind") or "unavailable"),
        )
    completion = approval_result["completion"]
    after = {
        "reviewer_review": deepcopy(review_data.get("reviewer_review")),
        "active_head_sha": review_data.get("active_head_sha"),
        "current_cycle_completion": deepcopy(review_data.get("current_cycle_completion")),
        "current_cycle_write_approval": deepcopy(review_data.get("current_cycle_write_approval")),
        "review_completed_at": review_data.get("review_completed_at"),
        "review_completed_by": review_data.get("review_completed_by"),
        "review_completion_source": review_data.get("review_completion_source"),
    }
    return before != after or bool(completion.get("completed"))


def reconcile_active_review_entry(
    bot: ReconcileRectifyRuntimeContext,
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False
    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.", True, False
    if require_pull_request_context and bot.get_config_value("IS_PULL_REQUEST", "false").lower() != "true":
        return f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only reconciles PR reviews.", True, False
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15" and bot.get_config_value("IS_PULL_REQUEST", "false").lower() == "true":
        return "ℹ️ PR review freshness rectify is epoch-gated and currently inactive.", True, False
    head_repair_result = bot.adapters.review_state.maybe_record_head_observation_repair(issue_number, review_data)
    state_changed = head_repair_result.changed
    try:
        reviews = _read_reconcile_reviews(bot, issue_number)
    except ReconcileReadError:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False
    messages: list[str] = []
    refreshed, latest_review = refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        reviews=reviews,
        actor=assigned_reviewer,
    )
    if latest_review is not None:
        latest_state = str(latest_review.get("state", "")).upper()
        if refreshed:
            state_changed = True
            messages.append(f"latest review by @{assigned_reviewer} is `{latest_state}`")
    if _record_review_rebuild(bot, state, issue_number, review_data):
        state_changed = True
        review_data["review_completion_source"] = completion_source
    if review_data.get("mandatory_approver_required"):
        from scripts.reviewer_bot_core import approval_policy

        escalation_opened_at = bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at")) or bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        triage_approval = approval_policy.find_triage_approval_after(bot, reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if bot.satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")
    if state_changed:
        return f"✅ Rectified PR #{issue_number}: {'; '.join(messages) or 'reconciled live review state'}.", True, True
    return f"ℹ️ Rectify checked PR #{issue_number}: {'; '.join(messages) or 'no reconciliation transitions applied'}.", True, False


def handle_rectify_command(
    bot: ReconcileRectifyRuntimeContext,
    state: dict,
    issue_number: int,
    comment_author: str,
    reviewer_authority: dict[str, object] | None = None,
) -> tuple[str, bool, bool]:
    request = type(
        "RectifyReviewerAuthorityRequest",
        (),
        {
            "issue_number": issue_number,
            "is_pull_request": bot.get_config_value("IS_PULL_REQUEST", "false").lower() == "true",
        },
    )()
    reviewer_authority = reviewer_authority or assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        request,
        actor=comment_author,
    )
    reviewer_authority = assignment_flow.require_reviewer_command_actor(reviewer_authority, comment_author)
    if reviewer_authority.get("authorized"):
        return reconcile_active_review_entry(bot, state, issue_number)
    return (
        assignment_flow.reviewer_command_authority_failure_message("rectify", reviewer_authority),
        False,
        False,
    )


def _load_deferred_context(bot: ReconcileWorkflowRuntimeContext) -> dict:
    return bot.load_deferred_payload()


def _is_missing_optional_router_payload_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return "Missing DEFERRED_CONTEXT_PATH" in message or "missing artifact" in message


def optional_router_payload_missing(bot: ReconcileWorkflowRuntimeContext, event_context) -> bool:
    if event_context.workflow_artifact_contract != "artifact_optional_router":
        return False
    try:
        _load_deferred_context(bot)
    except RuntimeError as exc:
        if not _is_missing_optional_router_payload_error(exc):
            raise
        return True
    return False


_DEFERRED_PARSE_ERRORS = (RuntimeError, KeyError, TypeError, ValueError)


def _payload_source_commit_id(payload: dict) -> str | None:
    source_commit_id = payload.get("source_commit_id")
    if not isinstance(source_commit_id, str) or not source_commit_id.strip():
        return None
    return source_commit_id.strip()


def _hydrate_live_review_comment_commit_id(
    context: DeferredCommentReplayContext,
    live_comment: dict,
) -> DeferredCommentReplayContext | None:
    if context.expected_event_name != "pull_request_review_comment":
        return context
    payload = context.payload.raw_payload
    source_commit_id = context.payload.source_commit_id or _payload_source_commit_id(payload)
    if source_commit_id is not None:
        payload["source_commit_id"] = source_commit_id
        if context.payload.source_commit_id == source_commit_id:
            return context
        return replace(context, payload=replace(context.payload, source_commit_id=source_commit_id))
    live_commit_id = live_comment.get("commit_id")
    if isinstance(live_commit_id, str) and live_commit_id.strip():
        source_commit_id = live_commit_id.strip()
        payload["source_commit_id"] = source_commit_id
        return replace(context, payload=replace(context.payload, source_commit_id=source_commit_id))
    return None


def _record_missing_review_comment_commit_id(
    bot: ReconcileWorkflowRuntimeContext,
    review_data: dict,
    payload: dict,
    *,
    failure_kind: str | None = "invalid_payload",
) -> bool:
    return gap_bookkeeping.record_deferred_gap_diagnostic(
        bot,
        review_data,
        payload,
        "artifact_invalid",
        (
            "Deferred review comment artifact source_commit_id could not be recovered from live review comment; "
            f"replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
        ),
        failure_kind=failure_kind,
    )


def _classify_deferred_comment_payload(payload: DeferredCommentPayload) -> dict:
    if payload.source_comment_class is not None and payload.source_has_non_command_text is not None:
        return {
            "comment_class": payload.source_comment_class,
            "has_non_command_text": payload.source_has_non_command_text,
            "command_count": 1 if payload.source_comment_class in {"command_only", "command_plus_text"} else 0,
        }
    normalized_body = "\n".join(line.rstrip() for line in payload.comment_body.replace("\r\n", "\n").split("\n")).strip()
    classified = comment_routing_policy.classify_comment_payload(
        "@guidelines-bot",
        normalized_body,
        None,
    )
    return {
        "comment_class": classified.get("comment_class", ObserverCommentClassification.PLAIN_TEXT),
        "has_non_command_text": bool(classified.get("has_non_command_text")),
        "command_count": int(classified.get("command_count", 0)),
    }


def _deferred_comment_body_digest_matches(payload: DeferredCommentPayload, live_body: str) -> bool:
    if payload.source_body_digest is not None:
        return digest_comment_body(live_body) == payload.source_body_digest
    return digest_comment_body(live_body) == digest_comment_body(payload.comment_body)


def _reconcile_deferred_comment(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    review_data: dict,
    context: DeferredCommentReplayContext,
    admission: WorkflowRunReplayAdmission | None = None,
) -> bool:
    if admission is None:
        admission = build_workflow_run_replay_admission(
            source_event_key=context.source_event_key,
            triggering_conclusion="success",
            payload_kind=context.payload.identity.payload_kind.value,
            source_authority_status="trusted_exact_identity",
            payload_valid=True,
            identity_present=True,
        )
    payload = context.payload.raw_payload
    comment_id = context.comment_id
    pr_number = context.pr_number
    live_pr_context = _read_live_pr_replay_context(bot, pr_number)
    source_freshness_eligible = context.source_freshness_eligible
    source_classified = _classify_deferred_comment_payload(context.payload)

    def replay_request(comment_context: LiveCommentReplayContext | None = None, *, comment_body: str = "") -> CommentEventRequest:
        return build_replay_comment_event_request(
            context.payload,
            live_comment=comment_context,
            live_pr=live_pr_context,
            comment_body=comment_body,
        )

    def record_artifact_invalid(problem: InvalidEventInput) -> bool:
        return gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            payload,
            "artifact_invalid",
            str(problem),
        )

    try:
        live_comment = _read_reconcile_object(bot, context.live_comment_endpoint, label=f"deferred comment {comment_id}")
    except ReconcileReadError as exc:
        if context.expected_event_name == "pull_request_review_comment" and _payload_source_commit_id(payload) is None:
            return _record_missing_review_comment_commit_id(
                bot,
                review_data,
                payload,
                failure_kind=exc.failure_kind,
            )
        decision = reconcile_replay_policy.decide_comment_replay(
            comment_id=comment_id,
            source_comment_class=str(source_classified.get("comment_class", ObserverCommentClassification.PLAIN_TEXT)),
            source_has_non_command_text=bool(source_classified.get("has_non_command_text")),
            source_freshness_eligible=source_freshness_eligible,
            live_comment_found=False,
            live_body_digest_matches=False,
            live_classified=None,
            live_failure_kind=exc.failure_kind,
            runbook_path=bot.REVIEW_FRESHNESS_RUNBOOK_PATH,
        )
        changed = False
        if decision.record_source_freshness:
            try:
                changed = record_conversation_freshness(bot, state, replay_request())
            except InvalidEventInput as exc:
                return record_artifact_invalid(exc)
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            payload,
            str(decision.failed_closed_reason),
            str(decision.diagnostic_summary),
            failure_kind=decision.failure_kind,
        )
        return changed or gap_changed
    hydrated_context = _hydrate_live_review_comment_commit_id(context, live_comment)
    if hydrated_context is None:
        return _record_missing_review_comment_commit_id(bot, review_data, payload)
    context = hydrated_context
    comment_context = _read_live_comment_replay_context(live_comment, payload)
    live_body = live_comment.get("body")
    if not isinstance(live_body, str):
        raise RuntimeError("Live deferred comment body is unavailable")
    live_classified = classify_comment_payload(bot, live_body)
    if not _deferred_comment_body_digest_matches(context.payload, live_body):
        decision = reconcile_replay_policy.decide_comment_replay(
            comment_id=comment_id,
            source_comment_class=str(source_classified.get("comment_class", ObserverCommentClassification.PLAIN_TEXT)),
            source_has_non_command_text=bool(source_classified.get("has_non_command_text")),
            source_freshness_eligible=source_freshness_eligible,
            live_comment_found=True,
            live_body_digest_matches=False,
            live_classified={
                "comment_class": str(live_classified.get("comment_class", "plain_text")),
                "has_non_command_text": bool(live_classified.get("has_non_command_text")),
                "command_count": 1,
            },
            live_failure_kind=None,
            runbook_path=bot.REVIEW_FRESHNESS_RUNBOOK_PATH,
        )
        changed = False
        if decision.record_source_freshness:
            try:
                changed = record_conversation_freshness(bot, state, replay_request(comment_context, comment_body=live_body))
            except InvalidEventInput as exc:
                return record_artifact_invalid(exc)
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            payload,
            str(decision.failed_closed_reason),
            str(decision.diagnostic_summary),
        )
        return changed or gap_changed
    decision = reconcile_replay_policy.decide_comment_replay(
        comment_id=int(payload["comment_id"]),
        source_comment_class=str(source_classified.get("comment_class", ObserverCommentClassification.PLAIN_TEXT)),
        source_has_non_command_text=bool(source_classified.get("has_non_command_text")),
        source_freshness_eligible=source_freshness_eligible,
        live_comment_found=True,
        live_body_digest_matches=True,
        live_classified=live_classified,
        live_failure_kind=None,
        runbook_path=bot.REVIEW_FRESHNESS_RUNBOOK_PATH,
    )
    changed = False
    if decision.record_source_freshness:
        try:
            changed = record_conversation_freshness(bot, state, replay_request(comment_context, comment_body=live_body)) or changed
        except InvalidEventInput as exc:
            return record_artifact_invalid(exc)
    if decision.failed_closed_reason is not None:
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            payload,
            decision.failed_closed_reason,
            str(decision.diagnostic_summary),
            failure_kind=decision.failure_kind,
        )
        return changed or gap_changed
    source_event_key = str(payload.get("source_event_key", ""))
    command_state_changed = False
    command_receipt = None
    if decision.replay_comment_command:
        command_receipt = _persisted_command_replay_receipt(
            review_data,
            source_event_key,
            admission=admission,
        )
    if decision.replay_comment_command and command_receipt is None:
        try:
            command_state_changed = process_comment_event(
                bot,
                state,
                replay_request(comment_context, comment_body=live_body),
                classify_comment_payload=lambda _bot, _body: live_classified,
                classify_issue_comment_actor=classify_issue_comment_actor,
            )
            changed = command_state_changed or changed
        except InvalidEventInput as exc:
            return record_artifact_invalid(exc)
    if command_receipt is None:
        command_receipt = apply_reconcile_command_with_receipt(
            bot,
            state,
            ReconcileTarget(
                pr_number=pr_number,
                source_event_key=source_event_key,
                payload_kind=context.payload.identity.payload_kind.value,
                parsed_payload={
                    "command_name": str(live_classified.get("command")) if live_classified.get("command") else None,
                    "replay_attempted": bool(decision.replay_comment_command),
                    "command_side_effects_attempted": ("comment_command",) if decision.replay_comment_command else (),
                    "state_save_required": command_state_changed,
                    "state_save_succeeded": not command_state_changed,
                    "mark_reconciled_requested": bool(decision.mark_reconciled),
                    "clear_gap_requested": bool(decision.clear_gap),
                },
                recovered_identity=None,
                live_pr_state="open",
                admission=admission,
            ),
        )
    if command_receipt.replay_attempted or not admission.replay_allowed:
        changed = _store_command_replay_receipt(review_data, command_receipt) or changed
    reconciled_changed = False
    if (
        decision.mark_reconciled
        and admission.mark_reconciled_allowed
        and command_receipt.result == "pass_replayed_and_persisted"
    ):
        reconciled_changed = gap_bookkeeping.mark_reconciled_source_event(
            review_data,
            source_event_key,
            reconciled_at=_now_iso(bot),
        )
        gap_cleared_changed = False
        if decision.clear_gap and admission.clear_gap_allowed:
            gap_cleared_changed = gap_bookkeeping.clear_deferred_gap(review_data, source_event_key)
        return changed or reconciled_changed or gap_cleared_changed
    return changed


def _handle_issue_comment_workflow_run(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    review_data: dict,
    parsed_payload: DeferredCommentPayload,
    admission: WorkflowRunReplayAdmission,
) -> bool:
    _reconcile_payloads.validate_triggering_run_identity(bot, parsed_payload.raw_payload)
    context = build_deferred_comment_replay_context(
        parsed_payload,
        expected_event_name="issue_comment",
        live_comment_endpoint=f"issues/comments/{parsed_payload.comment_id}",
    )
    return _reconcile_deferred_comment(bot, state, review_data, context, admission)


def _handle_review_comment_workflow_run(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    review_data: dict,
    parsed_payload: DeferredCommentPayload,
    admission: WorkflowRunReplayAdmission,
) -> bool:
    _reconcile_payloads.validate_triggering_run_identity(bot, parsed_payload.raw_payload)
    context = build_deferred_comment_replay_context(
        parsed_payload,
        expected_event_name="pull_request_review_comment",
        live_comment_endpoint=f"pulls/comments/{parsed_payload.comment_id}",
    )
    return _reconcile_deferred_comment(bot, state, review_data, context, admission)


def _handle_review_submitted_workflow_run(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    review_data: dict,
    parsed_payload: DeferredReviewPayload,
    admission: WorkflowRunReplayAdmission,
) -> bool:
    _reconcile_payloads.validate_triggering_run_identity(bot, parsed_payload.raw_payload)
    context = build_deferred_review_replay_context(
        parsed_payload,
        expected_event_action="submitted",
    )
    pr_number = context.pr_number
    source_event_key = context.source_event_key
    review_id = context.review_id
    actor = context.actor_login
    live_review = _read_optional_reconcile_object(bot, f"pulls/{pr_number}/reviews/{review_id}", label=f"live review #{review_id}")
    live_pr = _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number}")
    live_commit_id = None
    live_submitted_at = parsed_payload.source_submitted_at
    live_state = parsed_payload.source_review_state
    if isinstance(live_review, dict):
        live_commit_id = live_review.get("commit_id")
        live_submitted_at = live_review.get("submitted_at") or live_submitted_at
        live_state = live_review.get("state") or live_state
    head = live_pr.get("head") if isinstance(live_pr, dict) else None
    current_head_sha = head.get("sha") if isinstance(head, dict) and isinstance(head.get("sha"), str) else None
    live_observation = LiveReviewObservation(
        review_id=review_id,
        live_found=isinstance(live_review, dict),
        read_status="pass" if isinstance(live_review, dict) else "not_found",
        visibility_status="visible" if isinstance(live_review, dict) else "missing",
        commit_id=live_commit_id if isinstance(live_commit_id, str) else None,
        submitted_at=live_submitted_at if isinstance(live_submitted_at, str) else None,
        state=live_state if isinstance(live_state, str) else None,
        author=actor,
        failure_kind=None,
        diagnostic_reason=None if isinstance(live_review, dict) else "live_review_not_found",
    )
    if not isinstance(live_review, dict):
        live_commit_id = parsed_payload.source_commit_id
    state_changed = bot.adapters.review_state.maybe_record_head_observation_repair(pr_number, review_data).changed
    decision = decide_review_submitted_replay_from_input(
        ReviewReplayDecisionInput(
            pr_number=pr_number,
            review_id=review_id,
            source_event_key=source_event_key,
            actor_login=actor,
            current_reviewer=review_data.get("current_reviewer"),
            live_observation=live_observation,
            current_head_sha=current_head_sha,
            admission=admission,
        )
    )
    if decision.accept_reviewer_review:
        accept_channel_event(
            review_data,
            "reviewer_review",
            semantic_key=source_event_key,
            timestamp=str(decision.replay_timestamp),
            actor=str(decision.actor_login),
            reviewed_head_sha=str(decision.reviewed_head_sha),
            source_precedence=1,
        )
        record_reviewer_activity(review_data, str(decision.replay_timestamp))
        state_changed = True
    if _record_review_rebuild(bot, state, pr_number, review_data):
        state_changed = True
    reconciled_changed = False
    gap_cleared_changed = False
    if decision.mark_reconciled and admission.mark_reconciled_allowed:
        reconciled_changed = gap_bookkeeping.mark_reconciled_source_event(
            review_data,
            source_event_key,
            reconciled_at=_now_iso(bot),
        )
    if decision.clear_gap and admission.clear_gap_allowed:
        gap_cleared_changed = gap_bookkeeping.clear_deferred_gap(review_data, source_event_key)
    return state_changed or reconciled_changed or gap_cleared_changed


def _handle_review_dismissed_workflow_run(
    bot: ReconcileWorkflowRuntimeContext,
    state: dict,
    review_data: dict,
    parsed_payload: DeferredReviewPayload,
    admission: WorkflowRunReplayAdmission,
) -> bool:
    _reconcile_payloads.validate_triggering_run_identity(bot, parsed_payload.raw_payload)
    context = build_deferred_review_replay_context(
        parsed_payload,
        expected_event_action="dismissed",
    )
    source_event_key = context.source_event_key
    dismissal_time = _resolve_review_dismissal_time(
        bot,
        context.pr_number,
        context.review_id,
        parsed_payload.raw_payload,
    )
    dismissal_plan = reconcile_replay_policy.decide_review_dismissed_replay_plan(
        source_event_key=source_event_key,
        dismissal_timestamp=str(dismissal_time.timestamp) if dismissal_time.timestamp is not None else None,
        dismissal_exact=dismissal_time.exact,
        live_pr_readable=True,
    )
    if not dismissal_plan.record_channel_event:
        state_changed = bot.adapters.review_state.maybe_record_head_observation_repair(context.pr_number, review_data).changed
        live_pr_readable = True
        if dismissal_plan.rebuild_live_approval:
            try:
                state_changed = _record_review_rebuild(bot, state, context.pr_number, review_data) or state_changed
            except (AssertionError, ReconcileReadError):
                live_pr_readable = False
        if not live_pr_readable:
            dismissal_plan = reconcile_replay_policy.decide_review_dismissed_replay_plan(
                source_event_key=source_event_key,
                dismissal_timestamp=None,
                dismissal_exact=False,
                live_pr_readable=False,
            )
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            parsed_payload.raw_payload,
            "reconcile_failed_closed",
            (
                f"Deferred review dismissal {context.review_id} lacks exact source dismissal time; "
                f"dismissal replay suppressed ({dismissal_time.reason or 'unavailable'}). "
                f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
            failure_kind=dismissal_time.failure_kind or dismissal_plan.failure_kind,
        )
        return state_changed or gap_changed
    state_changed = False
    if dismissal_plan.record_channel_event and admission.replay_allowed:
        state_changed = accept_channel_event(
            review_data,
            "review_dismissal",
            semantic_key=source_event_key,
            timestamp=str(dismissal_plan.replay_timestamp),
            dismissal_only=True,
        ) or state_changed
    state_changed = bot.adapters.review_state.maybe_record_head_observation_repair(context.pr_number, review_data).changed or state_changed
    if dismissal_plan.rebuild_live_approval:
        state_changed = _record_review_rebuild(bot, state, context.pr_number, review_data) or state_changed
    reconciled_changed = False
    if dismissal_plan.mark_reconciled and admission.mark_reconciled_allowed:
        reconciled_changed = gap_bookkeeping.mark_reconciled_source_event(
            review_data,
            source_event_key,
            reconciled_at=_now_iso(bot),
        )
    gap_cleared_changed = False
    if dismissal_plan.clear_gap and admission.clear_gap_allowed:
        gap_cleared_changed = gap_bookkeeping.clear_deferred_gap(review_data, source_event_key)
    return state_changed or reconciled_changed or gap_cleared_changed


_WORKFLOW_RUN_HANDLER_MATRIX: dict[tuple[str, str], tuple[type[DeferredCommentPayload] | type[DeferredReviewPayload], object]] = {
    ("issue_comment", "created"): (DeferredCommentPayload, _handle_issue_comment_workflow_run),
    ("pull_request_review_comment", "created"): (DeferredCommentPayload, _handle_review_comment_workflow_run),
    ("pull_request_review", "submitted"): (DeferredReviewPayload, _handle_review_submitted_workflow_run),
    ("pull_request_review", "dismissed"): (DeferredReviewPayload, _handle_review_dismissed_workflow_run),
}


def _workflow_run_handler_for_payload(parsed_payload: ParsedWorkflowRunPayload):
    entry = _WORKFLOW_RUN_HANDLER_MATRIX.get(
        (
            parsed_payload.identity.source_event_name,
            parsed_payload.identity.source_event_action,
        )
    )
    if entry is None:
        return None
    payload_type, handler = entry
    if not isinstance(parsed_payload, payload_type):
        return None
    return handler


def handle_workflow_run_event_result(bot: ReconcileWorkflowRuntimeContext, state: dict) -> WorkflowRunHandlerResult:
    bot.assert_lock_held("handle_workflow_run_event")
    event_context = build_event_context(bot)
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15":
        _log(bot, "info", "V18 workflow_run reconcile safe-noop before epoch flip")
        return WorkflowRunHandlerResult(False, [])

    def _build_result(state_changed: bool, pr_number: int) -> WorkflowRunHandlerResult:
        touched_items = bot.drain_touched_items()
        return WorkflowRunHandlerResult(
            state_changed=state_changed,
            touched_items=touched_items,
        )

    if event_context.workflow_run_triggering_conclusion != "success":
        try:
            payload = _load_deferred_context(bot)
            recovered_identity = _reconcile_payloads.recover_deferred_payload_identity(payload)
        except RuntimeError:
            _log(
                bot,
                "warning",
                "Non-success observer workflow_run had no recoverable deferred identity; retained diagnostic only.",
                workflow_conclusion=event_context.workflow_run_triggering_conclusion or "<missing>",
            )
            return WorkflowRunHandlerResult(False, [])
        pr_number = recovered_identity.pr_number
        review_data = ensure_review_entry(state, pr_number)
        if review_data is None:
            review_data, recovery_changed = _recover_missing_active_review_entry(
                bot,
                state,
                pr_number=pr_number,
                source_event_key=recovered_identity.source_event_key,
                source_event_name=recovered_identity.source_event_name,
                source_event_action=recovered_identity.source_event_action,
                allow_reconstruction=False,
            )
            if review_data is None:
                return _build_result(recovery_changed, pr_number)
        bot.collect_touched_item(pr_number)
        admission = build_workflow_run_replay_admission(
            source_event_key=recovered_identity.source_event_key,
            triggering_conclusion=event_context.workflow_run_triggering_conclusion,
            payload_kind=str(payload.get("payload_kind")) if isinstance(payload, dict) and payload.get("payload_kind") else None,
            source_authority_status="diagnostic_non_success_identity",
            payload_valid=isinstance(payload, dict),
            identity_present=True,
        )
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            recovered_identity.diagnostic_payload,
            "observer_failed" if event_context.workflow_run_triggering_conclusion != "cancelled" else "observer_cancelled",
            f"Deferred observer concluded {event_context.workflow_run_triggering_conclusion}; replay suppressed by {admission.admission_state}.",
            failure_kind=event_context.workflow_run_triggering_conclusion,
        )
        return _build_result(gap_changed, pr_number)

    try:
        payload = _load_deferred_context(bot)
    except RuntimeError as exc:
        if event_context.workflow_artifact_contract == "artifact_optional_router" and _is_missing_optional_router_payload_error(exc):
            return WorkflowRunHandlerResult(False, [])
        raise
    try:
        parsed_payload = parse_deferred_context_payload(payload)
    except _DEFERRED_PARSE_ERRORS as exc:
        try:
            recovered_identity = _reconcile_payloads.recover_deferred_payload_identity(payload)
        except RuntimeError as recover_exc:
            raise RuntimeError(f"{recover_exc}; original parse error: {exc}") from exc
        diagnostic_payload = recovered_identity.diagnostic_payload
        _reconcile_payloads.validate_triggering_run_identity(bot, diagnostic_payload)
        pr_number = recovered_identity.pr_number
        review_data = ensure_review_entry(state, pr_number)
        if review_data is None:
            _recovered_review_data, recovery_changed = _recover_missing_active_review_entry(
                bot,
                state,
                pr_number=pr_number,
                source_event_key=recovered_identity.source_event_key,
                source_event_name=recovered_identity.source_event_name,
                source_event_action=recovered_identity.source_event_action,
                allow_reconstruction=False,
            )
            return _build_result(recovery_changed, pr_number)
        try:
            live_pr_state = _read_live_pr_state_for_reconcile(bot, pr_number)
            if live_pr_state == "closed":
                _log(
                    bot,
                    "info",
                    f"Ignoring invalid deferred workflow_run for closed PR #{pr_number}",
                    issue_number=pr_number,
                    source_event_key=recovered_identity.source_event_key,
                )
                return WorkflowRunHandlerResult(False, [])
            if live_pr_state != "open":
                raise ReconcileReadError(
                    f"live PR #{pr_number} state is unsupported for replay: {live_pr_state}",
                    failure_kind="invalid_payload",
                )
        except RuntimeError as live_pr_exc:
            bot.collect_touched_item(pr_number)
            failure_kind = live_pr_exc.failure_kind if isinstance(live_pr_exc, ReconcileReadError) else None
            gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
                bot,
                review_data,
                diagnostic_payload,
                "reconcile_failed_closed",
                f"{live_pr_exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
                failure_kind=failure_kind,
            )
            if gap_changed:
                return _build_result(True, pr_number)
            raise
        bot.collect_touched_item(pr_number)
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            diagnostic_payload,
            "artifact_invalid",
            f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
            failure_kind="invalid_payload",
        )
        return _build_result(gap_changed, pr_number)
    pr_number = parsed_payload.pr_number
    if pr_number <= 0:
        raise RuntimeError("Deferred context is missing a valid PR number")
    review_data = ensure_review_entry(state, pr_number)
    if review_data is None:
        review_data, recovery_changed = _recover_missing_active_review_entry(
            bot,
            state,
            pr_number=pr_number,
            source_event_key=parsed_payload.identity.source_event_key,
            source_event_name=parsed_payload.identity.source_event_name,
            source_event_action=parsed_payload.identity.source_event_action,
        )
        if review_data is None:
            return _build_result(recovery_changed, pr_number)
    try:
        live_pr_state = _read_live_pr_state_for_reconcile(bot, pr_number)
        if live_pr_state == "closed":
            _log(
                bot,
                "info",
                f"Ignoring deferred workflow_run for closed PR #{pr_number}",
                issue_number=pr_number,
                source_event_key=parsed_payload.identity.source_event_key,
            )
            return WorkflowRunHandlerResult(False, [])
        if live_pr_state != "open":
            raise ReconcileReadError(
                f"live PR #{pr_number} state is unsupported for replay: {live_pr_state}",
                failure_kind="invalid_payload",
            )
        bot.collect_touched_item(pr_number)
        authority, admission = _admission_for_parsed_payload(
            parsed_payload,
            triggering_conclusion=event_context.workflow_run_triggering_conclusion or "success",
        )
        if not admission.replay_allowed:
            return _build_result(
                _record_blocked_admission_gap(bot, review_data, parsed_payload, authority, admission),
                pr_number,
            )
        handler = _workflow_run_handler_for_payload(parsed_payload)
        if handler is None:
            raise RuntimeError("Unsupported deferred workflow_run payload")
        return _build_result(handler(bot, state, review_data, parsed_payload, admission), pr_number)
    except RuntimeError as exc:
        bot.collect_touched_item(pr_number)
        failure_kind = exc.failure_kind if isinstance(exc, ReconcileReadError) else None
        gap_changed = gap_bookkeeping.record_deferred_gap_diagnostic(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
            failure_kind=failure_kind,
        )
        if gap_changed:
            return _build_result(True, pr_number)
        raise
