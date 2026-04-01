"""Trusted deferred reconcile helpers for reviewer-bot workflow_run processing."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass

from .comment_routing import (
    _digest_body,
    _handle_command,
    _record_conversation_freshness,
    classify_comment_payload,
)
from .reviews import (
    find_triage_approval_after,
    refresh_reviewer_review_from_live_preferred_review,
)


def _now_iso(bot) -> str:
    return bot.datetime.now(bot.timezone.utc).isoformat()


class ReconcileReadError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: str | None = None):
        super().__init__(message)
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class LiveCommentReplayValidationResult:
    live_classified: dict | None
    changed: bool
    failed_closed: bool


@dataclass(frozen=True)
class DeferredArtifactIdentity:
    schema_version: int
    source_workflow_name: str
    source_workflow_file: str
    source_run_id: int
    source_run_attempt: int
    source_event_name: str
    source_event_action: str
    source_event_key: str


@dataclass(frozen=True)
class DeferredReviewPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    review_id: int
    source_submitted_at: str | None
    source_review_state: str | None
    source_commit_id: str | None
    actor_login: str | None
    raw_payload: dict


@dataclass(frozen=True)
class DeferredCommentPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    comment_id: int
    comment_class: str
    has_non_command_text: bool
    source_body_digest: str
    source_created_at: str
    actor_login: str | None
    raw_payload: dict


@dataclass(frozen=True)
class ObserverNoopPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    reason: str
    raw_payload: dict


@dataclass(frozen=True)
class DeferredCommentReplayContext:
    payload: DeferredCommentPayload
    expected_event_name: str
    live_comment_endpoint: str

    @property
    def source_event_key(self) -> str:
        return self.payload.identity.source_event_key

    @property
    def comment_id(self) -> int:
        return self.payload.comment_id

    @property
    def pr_number(self) -> int:
        return self.payload.pr_number

    @property
    def actor_login(self) -> str:
        return self.payload.actor_login or ""

    @property
    def source_created_at(self) -> str:
        return self.payload.source_created_at

    @property
    def source_freshness_eligible(self) -> bool:
        return self.payload.comment_class in {"plain_text", "command_plus_text"} and self.payload.has_non_command_text


def _build_deferred_identity(payload: dict) -> DeferredArtifactIdentity:
    return DeferredArtifactIdentity(
        schema_version=int(payload["schema_version"]),
        source_workflow_name=str(payload["source_workflow_name"]),
        source_workflow_file=str(payload["source_workflow_file"]),
        source_run_id=int(payload["source_run_id"]),
        source_run_attempt=int(payload["source_run_attempt"]),
        source_event_name=str(payload["source_event_name"]),
        source_event_action=str(payload["source_event_action"]),
        source_event_key=str(payload["source_event_key"]),
    )


def build_deferred_comment_replay_context(
    payload: DeferredCommentPayload,
    *,
    expected_event_name: str,
    live_comment_endpoint: str,
) -> DeferredCommentReplayContext:
    if payload.identity.source_event_key != f"{expected_event_name}:{payload.comment_id}":
        raise RuntimeError("Deferred comment artifact source_event_key mismatch")
    return DeferredCommentReplayContext(
        payload=payload,
        expected_event_name=expected_event_name,
        live_comment_endpoint=live_comment_endpoint,
    )


def _read_reconcile_object(bot, endpoint: str, *, label: str) -> dict:
    try:
        response = bot.github_api_request("GET", endpoint, retry_policy="idempotent_read")
    except SystemExit:
        payload = bot.github_api("GET", endpoint)
        if not isinstance(payload, dict):
            raise ReconcileReadError(f"{label} unavailable", failure_kind="unavailable")
        return payload
    if not response.ok:
        failure_kind = response.failure_kind
        if failure_kind == "not_found":
            raise ReconcileReadError(f"{label} not found", failure_kind=failure_kind)
        raise ReconcileReadError(f"{label} unavailable", failure_kind=failure_kind)
    if not isinstance(response.payload, dict):
        raise ReconcileReadError(f"{label} payload invalid", failure_kind="invalid_payload")
    return response.payload


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    review_data.setdefault("deferred_gaps", {})
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    review_data["deferred_gaps"][source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> bool:
    deferred_gaps = review_data.get("deferred_gaps")
    if isinstance(deferred_gaps, dict):
        if source_event_key in deferred_gaps:
            deferred_gaps.pop(source_event_key, None)
            return True
    return False


def _mark_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.setdefault("reconciled_source_events", [])
    if source_event_key not in reconciled:
        reconciled.append(source_event_key)
        return True
    return False


def _was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.get("reconciled_source_events")
    return isinstance(reconciled, list) and source_event_key in reconciled


def _record_review_rebuild(bot, state: dict, issue_number: int, review_data: dict) -> bool:
    pull_request = _read_reconcile_object(bot, f"pulls/{issue_number}", label=f"pull request #{issue_number}")
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        raise ReconcileReadError(f"live reviews for PR #{issue_number} unavailable", failure_kind="unavailable")
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
    approval_result = bot.reviews_module.rebuild_pr_approval_state_result(
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
    bot,
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False
    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.", True, False
    if require_pull_request_context and os.environ.get("IS_PULL_REQUEST", "false").lower() != "true":
        return f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only reconciles PR reviews.", True, False
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15" and os.environ.get("IS_PULL_REQUEST", "false").lower() == "true":
        return "ℹ️ PR review freshness rectify is epoch-gated and currently inactive.", True, False
    head_repair_result = bot.maybe_record_head_observation_repair(issue_number, review_data)
    state_changed = head_repair_result.changed
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
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
        escalation_opened_at = bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at")) or bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        triage_approval = find_triage_approval_after(bot, reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if bot.satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")
    if state_changed:
        return f"✅ Rectified PR #{issue_number}: {'; '.join(messages) or 'reconciled live review state'}.", True, True
    return f"ℹ️ Rectify checked PR #{issue_number}: {'; '.join(messages) or 'no reconciliation transitions applied'}.", True, False


def _validate_deferred_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred comment artifact source digest or timestamp is malformed")


def _validate_deferred_review_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "review_id",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("review_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review artifact review_id and pr_number must be integers")


def _validate_deferred_review_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review-comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review-comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review-comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred review-comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred review-comment artifact source digest or timestamp is malformed")


def _load_deferred_context() -> dict:
    path = os.environ.get("DEFERRED_CONTEXT_PATH", "").strip()
    if not path:
        raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")
    return payload


def parse_deferred_context_payload(payload: dict) -> DeferredReviewPayload | DeferredCommentPayload | ObserverNoopPayload:
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")

    if payload.get("kind") == "observer_noop":
        _validate_observer_noop_payload(payload)
        return ObserverNoopPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            reason=str(payload["reason"]),
            raw_payload=payload,
        )

    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        _validate_deferred_comment_artifact(payload)
        return DeferredCommentPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            comment_id=int(payload["comment_id"]),
            comment_class=str(payload["comment_class"]),
            has_non_command_text=bool(payload["has_non_command_text"]),
            source_body_digest=str(payload["source_body_digest"]),
            source_created_at=str(payload["source_created_at"]),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    if event_name == "pull_request_review_comment" and event_action == "created":
        _validate_deferred_review_comment_artifact(payload)
        return DeferredCommentPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            comment_id=int(payload["comment_id"]),
            comment_class=str(payload["comment_class"]),
            has_non_command_text=bool(payload["has_non_command_text"]),
            source_body_digest=str(payload["source_body_digest"]),
            source_created_at=str(payload["source_created_at"]),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    if event_name == "pull_request_review" and event_action in {"submitted", "dismissed"}:
        _validate_deferred_review_artifact(payload)
        return DeferredReviewPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            review_id=int(payload["review_id"]),
            source_submitted_at=(
                str(payload["source_submitted_at"]) if payload.get("source_submitted_at") is not None else None
            ),
            source_review_state=(
                str(payload["source_review_state"]) if payload.get("source_review_state") is not None else None
            ),
            source_commit_id=(
                str(payload["source_commit_id"]) if payload.get("source_commit_id") is not None else None
            ),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    raise RuntimeError("Unsupported deferred workflow_run payload")


def _set_env_if_present(name: str, value) -> None:
    if value is None:
        return
    os.environ[name] = str(value)


def _hydrate_reconcile_pr_context(bot, pr_number: int) -> dict:
    pull_request = _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number} for reconcile context")
    author = pull_request.get("user")
    if not isinstance(author, dict):
        raise RuntimeError(f"Live PR #{pr_number} is missing author metadata")
    author_login = author.get("login")
    if not isinstance(author_login, str) or not author_login.strip():
        raise RuntimeError(f"Live PR #{pr_number} is missing a valid author login")
    labels = pull_request.get("labels")
    if labels is None:
        labels = []
    if not isinstance(labels, list):
        raise RuntimeError(f"Live PR #{pr_number} labels are malformed")
    label_names: list[str] = []
    for label in labels:
        if not isinstance(label, dict):
            raise RuntimeError(f"Live PR #{pr_number} contains malformed label metadata")
        name = label.get("name")
        if not isinstance(name, str):
            raise RuntimeError(f"Live PR #{pr_number} contains a label without a valid name")
        label_names.append(name)
    os.environ["IS_PULL_REQUEST"] = "true"
    os.environ["ISSUE_AUTHOR"] = author_login
    os.environ["ISSUE_LABELS"] = json.dumps(label_names)
    return pull_request


def _hydrate_reconcile_comment_context(live_comment: dict, payload: dict) -> None:
    user = live_comment.get("user")
    if not isinstance(user, dict):
        raise RuntimeError("Live deferred comment user metadata is unavailable")
    comment_author = user.get("login") or payload.get("actor_login") or ""
    if not isinstance(comment_author, str) or not comment_author.strip():
        raise RuntimeError("Live deferred comment author login is unavailable")
    comment_user_type = user.get("type")
    if not isinstance(comment_user_type, str) or not comment_user_type.strip():
        raise RuntimeError("Live deferred comment user type is unavailable")
    author_association = live_comment.get("author_association")
    if not isinstance(author_association, str) or not author_association.strip():
        raise RuntimeError("Live deferred comment author association is unavailable")
    _set_env_if_present("COMMENT_AUTHOR", comment_author)
    _set_env_if_present("COMMENT_ID", payload.get("comment_id"))
    _set_env_if_present("COMMENT_SOURCE_EVENT_KEY", payload.get("source_event_key"))
    _set_env_if_present("COMMENT_CREATED_AT", payload.get("source_created_at"))
    _set_env_if_present("COMMENT_USER_TYPE", comment_user_type)
    _set_env_if_present("COMMENT_AUTHOR_ASSOCIATION", author_association)
    _set_env_if_present("COMMENT_SENDER_TYPE", comment_user_type)
    os.environ["COMMENT_INSTALLATION_ID"] = ""
    os.environ["COMMENT_PERFORMED_VIA_GITHUB_APP"] = "true" if live_comment.get("performed_via_github_app") else "false"


def _validate_observer_noop_payload(payload: dict) -> None:
    required = {
        "schema_version",
        "kind",
        "reason",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Observer no-op payload missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 1:
        raise RuntimeError("Observer no-op payload schema_version is not accepted")
    if payload.get("kind") != "observer_noop":
        raise RuntimeError("Observer no-op payload kind mismatch")
    if not isinstance(payload.get("reason"), str) or not payload.get("reason"):
        raise RuntimeError("Observer no-op payload reason must be a non-empty string")
    if not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Observer no-op payload pr_number must be an integer")


def _expected_observer_identity(payload: dict) -> tuple[str, str]:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return (
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "submitted":
        return (
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "dismissed":
        return (
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        )
    if event_name == "pull_request_review_comment" and event_action == "created":
        return (
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
        )
    raise RuntimeError("Unsupported deferred workflow identity")


def _validate_workflow_run_artifact_identity(payload: dict) -> None:
    expected_name, expected_file = _expected_observer_identity(payload)
    if payload.get("source_workflow_name") != expected_name:
        raise RuntimeError("Deferred artifact workflow name mismatch")
    if payload.get("source_workflow_file") != expected_file:
        raise RuntimeError("Deferred artifact workflow file mismatch")
    triggering_name = os.environ.get("WORKFLOW_RUN_TRIGGERING_NAME", "").strip()
    if triggering_name and triggering_name != expected_name:
        raise RuntimeError("Triggering workflow name mismatch")
    triggering_id = os.environ.get("WORKFLOW_RUN_TRIGGERING_ID", "").strip()
    if triggering_id and str(payload.get("source_run_id")) != triggering_id:
        raise RuntimeError("Deferred artifact run_id mismatch")
    triggering_attempt = os.environ.get("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "").strip()
    if triggering_attempt and str(payload.get("source_run_attempt")) != triggering_attempt:
        raise RuntimeError("Deferred artifact run_attempt mismatch")
    if os.environ.get("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "").strip() != "success":
        raise RuntimeError("Triggering observer workflow did not conclude successfully")


def _artifact_expected_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    run_id = payload.get("source_run_id")
    run_attempt = payload.get("source_run_attempt")
    if event_name == "issue_comment" and event_action == "created":
        return f"reviewer-bot-comment-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "submitted":
        return f"reviewer-bot-review-submitted-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return f"reviewer-bot-review-dismissed-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review_comment" and event_action == "created":
        return f"reviewer-bot-review-comment-context-{run_id}-attempt-{run_attempt}"
    raise RuntimeError("Unsupported deferred artifact naming")


def _artifact_expected_payload_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return "deferred-comment.json"
    if event_name == "pull_request_review" and event_action == "submitted":
        return "deferred-review-submitted.json"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return "deferred-review-dismissed.json"
    if event_name == "pull_request_review_comment" and event_action == "created":
        return "deferred-review-comment.json"
    raise RuntimeError("Unsupported deferred payload path")


def _reconcile_deferred_comment(
    bot,
    state: dict,
    review_data: dict,
    context: DeferredCommentReplayContext,
) -> bool:
    payload = context.payload.raw_payload
    comment_id = context.comment_id
    pr_number = context.pr_number
    _set_env_if_present("COMMENT_SOURCE_EVENT_KEY", context.source_event_key)
    _hydrate_reconcile_pr_context(bot, pr_number)
    comment_author = context.actor_login
    comment_created_at = context.source_created_at
    source_freshness_eligible = context.source_freshness_eligible
    try:
        live_comment = _read_reconcile_object(bot, context.live_comment_endpoint, label=f"deferred comment {comment_id}")
    except ReconcileReadError as exc:
        changed = False
        if source_freshness_eligible:
            changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
        if exc.failure_kind == "not_found":
            summary = (
                f"Deferred comment {comment_id} is no longer visible; source-time freshness only may be preserved. "
                f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            )
        else:
            summary = (
                f"Deferred comment {comment_id} could not be validated from live GitHub data "
                f"({exc.failure_kind or 'unavailable'}); replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            )
        gap_changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            summary,
            failure_kind=exc.failure_kind,
        )
        return changed or gap_changed
    _hydrate_reconcile_comment_context(live_comment, payload)
    live_body = live_comment.get("body")
    if not isinstance(live_body, str):
        raise RuntimeError("Live deferred comment body is unavailable")
    if _digest_body(live_body) != payload.get("source_body_digest"):
        changed = False
        if source_freshness_eligible:
            changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
        gap_changed = _update_deferred_gap(bot, review_data, payload, "reconcile_failed_closed", f"Deferred comment {comment_id} body digest changed; command execution suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
        return changed or gap_changed
    changed = False
    if source_freshness_eligible:
        changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at) or changed
    validation_result = _validate_live_comment_replay_contract(
        bot,
        review_data,
        payload,
        live_body,
    )
    if validation_result.live_classified is None:
        return changed or validation_result.changed
    live_classified = validation_result.live_classified
    if context.payload.comment_class in {"command_only", "command_plus_text"}:
        changed = _handle_command(bot, state, pr_number, comment_author, live_classified) or changed
    reconciled_changed = _mark_reconciled_source_event(review_data, str(payload.get("source_event_key", "")))
    gap_cleared_changed = _clear_source_event_key(review_data, str(payload.get("source_event_key", "")))
    return changed or reconciled_changed or gap_cleared_changed


def _update_deferred_gap(
    bot,
    review_data: dict,
    payload: dict,
    reason: str,
    diagnostic_summary: str,
    *,
    failure_kind: str | None = None,
) -> bool:
    source_event_key = str(payload.get("source_event_key", ""))
    if not source_event_key:
        return False
    review_data.setdefault("deferred_gaps", {})
    existing = review_data["deferred_gaps"].get(source_event_key, {})
    if not isinstance(existing, dict):
        existing = {}
    previous = deepcopy(existing)
    existing.update(
        {
            "source_event_key": source_event_key,
            "source_event_kind": f"{payload.get('source_event_name')}:{payload.get('source_event_action')}",
            "pr_number": payload.get("pr_number"),
            "reason": reason,
            "source_event_created_at": payload.get("source_created_at") or payload.get("source_submitted_at"),
            "source_run_id": payload.get("source_run_id"),
            "source_run_attempt": payload.get("source_run_attempt"),
            "source_workflow_file": payload.get("source_workflow_file"),
            "source_artifact_name": payload.get("source_artifact_name"),
            "first_noted_at": existing.get("first_noted_at") or _now_iso(bot),
            "last_checked_at": _now_iso(bot),
            "operator_action_required": True,
            "diagnostic_summary": diagnostic_summary,
            "failure_kind": failure_kind,
        }
    )
    changed = previous != existing
    review_data["deferred_gaps"][source_event_key] = existing
    return changed


def _validate_live_comment_replay_contract(
    bot,
    review_data: dict,
    payload: dict,
    live_body: str,
) -> LiveCommentReplayValidationResult:
    source_comment_class = str(payload.get("comment_class", ""))
    live_classified = classify_comment_payload(bot, live_body)
    live_comment_class = str(live_classified.get("comment_class", ""))
    source_has_non_command_text = bool(payload.get("has_non_command_text"))
    live_has_non_command_text = bool(live_classified.get("has_non_command_text"))

    if live_comment_class != source_comment_class:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} classification changed from "
                f"{source_comment_class} to {live_comment_class}; replay suppressed. "
                f"See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    if live_has_non_command_text != source_has_non_command_text:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} non-command text classification drifted; "
                f"replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    if source_comment_class in {"command_only", "command_plus_text"} and int(live_classified.get("command_count", 0)) != 1:
        changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            (
                f"Deferred comment {payload['comment_id']} no longer resolves to exactly one command; "
                f"replay suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}."
            ),
        )
        return LiveCommentReplayValidationResult(None, changed, True)

    return LiveCommentReplayValidationResult(live_classified, False, False)


def handle_workflow_run_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_workflow_run_event")
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15":
        print("V18 workflow_run reconcile safe-noop before epoch flip")
        return False
    payload = _load_deferred_context()
    parsed_payload = parse_deferred_context_payload(payload)
    pr_number = parsed_payload.pr_number
    if pr_number <= 0:
        raise RuntimeError("Deferred context is missing a valid PR number")
    bot.collect_touched_item(pr_number)
    review_data = bot.ensure_review_entry(state, pr_number, create=True)
    if review_data is None:
        raise RuntimeError(f"No review entry available for PR #{pr_number}")
    event_name = parsed_payload.identity.source_event_name
    event_action = parsed_payload.identity.source_event_action
    source_event_key = parsed_payload.identity.source_event_key
    try:
        if isinstance(parsed_payload, ObserverNoopPayload):
            _validate_workflow_run_artifact_identity(parsed_payload.raw_payload)
            print(
                "Observer workflow produced explicit no-op payload for "
                f"{source_event_key}: {parsed_payload.reason}"
            )
            return False

        if event_name == "issue_comment" and isinstance(parsed_payload, DeferredCommentPayload):
            _validate_workflow_run_artifact_identity(parsed_payload.raw_payload)
            context = build_deferred_comment_replay_context(
                parsed_payload,
                expected_event_name="issue_comment",
                live_comment_endpoint=f"issues/comments/{parsed_payload.comment_id}",
            )
            return _reconcile_deferred_comment(
                bot,
                state,
                review_data,
                context,
            )

        if event_name == "pull_request_review_comment" and event_action == "created" and isinstance(parsed_payload, DeferredCommentPayload):
            _validate_workflow_run_artifact_identity(parsed_payload.raw_payload)
            context = build_deferred_comment_replay_context(
                parsed_payload,
                expected_event_name="pull_request_review_comment",
                live_comment_endpoint=f"pulls/comments/{parsed_payload.comment_id}",
            )
            return _reconcile_deferred_comment(
                bot,
                state,
                review_data,
                context,
            )

        if event_name == "pull_request_review" and event_action == "submitted" and isinstance(parsed_payload, DeferredReviewPayload):
            _validate_workflow_run_artifact_identity(parsed_payload.raw_payload)
            review_id = parsed_payload.review_id
            if source_event_key != f"pull_request_review:{review_id}":
                raise RuntimeError("Deferred review-submitted artifact source_event_key mismatch")
            try:
                live_review = _read_reconcile_object(bot, f"pulls/{pr_number}/reviews/{review_id}", label=f"live review #{review_id}")
            except ReconcileReadError as exc:
                if exc.failure_kind == "not_found":
                    live_review = None
                else:
                    raise
            _read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number}")
            live_commit_id = None
            live_submitted_at = parsed_payload.source_submitted_at
            live_state = parsed_payload.source_review_state
            if isinstance(live_review, dict):
                live_commit_id = live_review.get("commit_id")
                live_submitted_at = live_review.get("submitted_at") or live_submitted_at
                live_state = live_review.get("state") or live_state
            else:
                live_commit_id = parsed_payload.source_commit_id
            actor = parsed_payload.actor_login or ""
            state_changed = bot.maybe_record_head_observation_repair(pr_number, review_data).changed
            if isinstance(review_data.get("current_reviewer"), str) and review_data.get("current_reviewer", "").lower() == actor.lower() and isinstance(live_commit_id, str) and isinstance(live_submitted_at, str):
                bot.reviews_module.accept_channel_event(
                    review_data,
                    "reviewer_review",
                    semantic_key=source_event_key,
                    timestamp=live_submitted_at,
                    actor=actor,
                    reviewed_head_sha=live_commit_id,
                    source_precedence=1,
                )
                bot.reviews_module.record_reviewer_activity(review_data, live_submitted_at)
                state_changed = True
            if _record_review_rebuild(bot, state, pr_number, review_data):
                state_changed = True
            reconciled_changed = _mark_reconciled_source_event(review_data, source_event_key)
            gap_cleared_changed = _clear_source_event_key(review_data, source_event_key)
            return state_changed or reconciled_changed or gap_cleared_changed

        if event_name == "pull_request_review" and event_action == "dismissed" and isinstance(parsed_payload, DeferredReviewPayload):
            _validate_workflow_run_artifact_identity(parsed_payload.raw_payload)
            review_id_value = parsed_payload.review_id
            if source_event_key != f"pull_request_review_dismissed:{review_id_value}":
                raise RuntimeError("Deferred review-dismissed artifact source_event_key mismatch")
            bot.reviews_module.accept_channel_event(
                review_data,
                "review_dismissal",
                semantic_key=source_event_key,
                timestamp=_now_iso(bot),
                dismissal_only=True,
            )
            state_changed = bot.maybe_record_head_observation_repair(pr_number, review_data).changed
            if _record_review_rebuild(bot, state, pr_number, review_data):
                state_changed = True
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return True
    except RuntimeError as exc:
        failure_kind = exc.failure_kind if isinstance(exc, ReconcileReadError) else None
        gap_changed = _update_deferred_gap(
            bot,
            review_data,
            payload,
            "reconcile_failed_closed",
            f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
            failure_kind=failure_kind,
        )
        if gap_changed:
            return True
        raise
    raise RuntimeError("Unsupported deferred workflow_run payload")
