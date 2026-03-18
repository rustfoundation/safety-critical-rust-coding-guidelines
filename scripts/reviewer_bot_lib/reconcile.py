"""Trusted deferred reconcile helpers for reviewer-bot workflow_run processing."""

from __future__ import annotations

import json
import os

from .comment_routing import (
    _digest_body,
    _handle_command,
    _record_conversation_freshness,
    classify_comment_payload,
)
from .reviews import find_triage_approval_after, get_latest_review_by_reviewer


def _now_iso(bot) -> str:
    return bot.datetime.now(bot.timezone.utc).isoformat()


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    review_data.setdefault("deferred_gaps", {})
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    review_data["deferred_gaps"][source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> None:
    deferred_gaps = review_data.get("deferred_gaps")
    if isinstance(deferred_gaps, dict):
        deferred_gaps.pop(source_event_key, None)


def _mark_reconciled_source_event(review_data: dict, source_event_key: str) -> None:
    reconciled = review_data.setdefault("reconciled_source_events", [])
    if source_event_key not in reconciled:
        reconciled.append(source_event_key)


def _was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.get("reconciled_source_events")
    return isinstance(reconciled, list) and source_event_key in reconciled


def _record_review_rebuild(bot, state: dict, issue_number: int, review_data: dict) -> bool:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch pull request #{issue_number}")
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        raise RuntimeError(f"Failed to fetch live reviews for PR #{issue_number}")
    completion, _ = bot.reviews_module.rebuild_pr_approval_state(bot, issue_number, review_data, pull_request=pull_request, reviews=reviews)
    if completion is None:
        raise RuntimeError(f"Unable to rebuild approval state for PR #{issue_number}")
    latest = get_latest_review_by_reviewer(bot, reviews, str(review_data.get("current_reviewer", "")))
    if latest is not None:
        commit_id = latest.get("commit_id")
        submitted_at = latest.get("submitted_at")
        if isinstance(commit_id, str) and isinstance(submitted_at, str):
            bot.reviews_module.accept_channel_event(
                review_data,
                "reviewer_review",
                semantic_key=f"pull_request_review:{latest.get('id')}",
                timestamp=submitted_at,
                actor=review_data.get("current_reviewer"),
                reviewed_head_sha=commit_id,
                source_precedence=1,
            )
    return bool(completion.get("completed"))


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
    state_changed = bot.maybe_record_head_observation_repair(issue_number, review_data)
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False
    latest_review = get_latest_review_by_reviewer(bot, reviews, assigned_reviewer)
    messages: list[str] = []
    if latest_review is not None:
        latest_state = str(latest_review.get("state", "")).upper()
        commit_id = latest_review.get("commit_id")
        submitted_at = latest_review.get("submitted_at")
        if latest_state in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"} and isinstance(commit_id, str) and isinstance(submitted_at, str):
            state_changed = bot.reviews_module.accept_channel_event(
                review_data,
                "reviewer_review",
                semantic_key=f"pull_request_review:{latest_review.get('id')}",
                timestamp=submitted_at,
                actor=assigned_reviewer,
                reviewed_head_sha=commit_id,
                source_precedence=1,
            ) or state_changed
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


def _load_deferred_context() -> dict:
    path = os.environ.get("DEFERRED_CONTEXT_PATH", "").strip()
    if not path:
        raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")
    return payload


def _set_env_if_present(name: str, value) -> None:
    if value is None:
        return
    os.environ[name] = str(value)


def _hydrate_reconcile_pr_context(bot, pr_number: int) -> dict:
    pull_request = bot.github_api("GET", f"pulls/{pr_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch live PR #{pr_number} for reconcile context")
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
    raise RuntimeError("Unsupported deferred payload path")


def _update_deferred_gap(bot, review_data: dict, payload: dict, reason: str, diagnostic_summary: str) -> None:
    source_event_key = str(payload.get("source_event_key", ""))
    if not source_event_key:
        return
    review_data.setdefault("deferred_gaps", {})
    existing = review_data["deferred_gaps"].get(source_event_key, {})
    if not isinstance(existing, dict):
        existing = {}
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
        }
    )
    review_data["deferred_gaps"][source_event_key] = existing


def handle_workflow_run_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_workflow_run_event")
    if str(state.get("freshness_runtime_epoch", "")).strip() != "freshness_v15":
        print("V18 workflow_run reconcile safe-noop before epoch flip")
        return False
    payload = _load_deferred_context()
    pr_number = int(payload.get("pr_number", 0) or 0)
    if pr_number <= 0:
        raise RuntimeError("Deferred context is missing a valid PR number")
    bot.collect_touched_item(pr_number)
    review_data = bot.ensure_review_entry(state, pr_number, create=True)
    if review_data is None:
        raise RuntimeError(f"No review entry available for PR #{pr_number}")
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    source_event_key = str(payload.get("source_event_key", ""))
    try:
        if payload.get("kind") == "observer_noop":
            _validate_observer_noop_payload(payload)
            _validate_workflow_run_artifact_identity(payload)
            print(
                "Observer workflow produced explicit no-op payload for "
                f"{source_event_key}: {payload.get('reason')}"
            )
            return False

        if event_name == "issue_comment":
            _validate_deferred_comment_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            _hydrate_reconcile_pr_context(bot, pr_number)
            if source_event_key != f"issue_comment:{payload['comment_id']}":
                raise RuntimeError("Deferred comment artifact source_event_key mismatch")
            comment_author = str(payload.get("actor_login", ""))
            comment_created_at = str(payload.get("source_created_at"))
            comment_id_value = payload.get("comment_id")
            if not isinstance(comment_id_value, int):
                raise RuntimeError("Deferred comment artifact comment_id must be an integer")
            comment_id = comment_id_value
            classified = payload.get("comment_class")
            source_freshness_eligible = classified in {"plain_text", "command_plus_text"} and bool(payload.get("has_non_command_text"))
            live_comment = bot.github_api("GET", f"issues/comments/{payload['comment_id']}")
            if not isinstance(live_comment, dict):
                changed = False
                if source_freshness_eligible:
                    changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
                _update_deferred_gap(bot, review_data, payload, "reconcile_failed_closed", f"Deferred comment {payload['comment_id']} is no longer visible; source-time freshness only may be preserved. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
                return changed
            _hydrate_reconcile_comment_context(live_comment, payload)
            live_body = live_comment.get("body")
            if not isinstance(live_body, str):
                raise RuntimeError("Live deferred comment body is unavailable")
            if _digest_body(live_body) != payload.get("source_body_digest"):
                changed = False
                if source_freshness_eligible:
                    changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
                _update_deferred_gap(bot, review_data, payload, "reconcile_failed_closed", f"Deferred comment {payload['comment_id']} body digest changed; command execution suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
                return changed
            changed = False
            if source_freshness_eligible:
                changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at) or changed
            if classified in {"command_only", "command_plus_text"}:
                live_classified = classify_comment_payload(bot, live_body)
                if int(live_classified.get("command_count", 0)) == 1:
                    changed = _handle_command(bot, state, pr_number, comment_author, live_classified) or changed
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return changed

        if event_name == "pull_request_review" and event_action == "submitted":
            _validate_deferred_review_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            review_id_value = payload.get("review_id")
            if not isinstance(review_id_value, int):
                raise RuntimeError("Deferred review artifact review_id must be an integer")
            review_id = review_id_value
            if source_event_key != f"pull_request_review:{review_id}":
                raise RuntimeError("Deferred review-submitted artifact source_event_key mismatch")
            live_review = bot.github_api("GET", f"pulls/{pr_number}/reviews/{review_id}")
            live_pr = bot.github_api("GET", f"pulls/{pr_number}")
            if not isinstance(live_pr, dict):
                raise RuntimeError(f"Failed to fetch live PR #{pr_number}")
            live_commit_id = None
            live_submitted_at = payload.get("source_submitted_at")
            live_state = payload.get("source_review_state")
            if isinstance(live_review, dict):
                live_commit_id = live_review.get("commit_id")
                live_submitted_at = live_review.get("submitted_at") or live_submitted_at
                live_state = live_review.get("state") or live_state
            else:
                live_commit_id = payload.get("source_commit_id")
            actor = str(payload.get("actor_login", ""))
            changed = bot.maybe_record_head_observation_repair(pr_number, review_data)
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
            _record_review_rebuild(bot, state, pr_number, review_data)
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return changed or True

        if event_name == "pull_request_review" and event_action == "dismissed":
            _validate_deferred_review_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            review_id_value = payload.get("review_id")
            if not isinstance(review_id_value, int):
                raise RuntimeError("Deferred review artifact review_id must be an integer")
            if source_event_key != f"pull_request_review_dismissed:{review_id_value}":
                raise RuntimeError("Deferred review-dismissed artifact source_event_key mismatch")
            bot.reviews_module.accept_channel_event(
                review_data,
                "review_dismissal",
                semantic_key=source_event_key,
                timestamp=_now_iso(bot),
                dismissal_only=True,
            )
            bot.maybe_record_head_observation_repair(pr_number, review_data)
            _record_review_rebuild(bot, state, pr_number, review_data)
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return True
    except RuntimeError as exc:
        _update_deferred_gap(bot, review_data, payload, "reconcile_failed_closed", f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
        raise
    raise RuntimeError("Unsupported deferred workflow_run payload")
