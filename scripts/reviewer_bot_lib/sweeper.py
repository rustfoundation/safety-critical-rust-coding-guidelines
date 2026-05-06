"""Deferred evidence sweeper, run correlation, and artifact correlation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.reviewer_bot_core import deferred_gap_diagnosis

from . import deferred_gap_bookkeeping as gap_bookkeeping
from . import retrying
from . import sweeper_observer_correlation as observer_correlation
from .review_state import (
    get_current_cycle_boundary,
    semantic_key_seen,
)
from .runtime_protocols import SweeperContext


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retention_days(bot: SweeperContext) -> int:
    return int(bot.get_config_value("DEFERRED_ARTIFACT_RETENTION_DAYS", "7") or 7)


def _github_repository(bot: SweeperContext) -> str:
    return bot.get_config_value("GITHUB_REPOSITORY", "")


def _approval_pending_signature_from_runbook() -> dict | None:
    return dict(deferred_gap_diagnosis.APPROVAL_PENDING_SIGNATURE)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_api_payload(bot: SweeperContext, endpoint: str) -> tuple[Any | None, str | None]:
    try:
        response = bot.github_api_request("GET", endpoint, retry_policy="idempotent_read", suppress_error_log=True)
    except SystemExit:
        payload = bot.github_api("GET", endpoint)
        return payload, None if payload is not None else "unavailable"
    if not response.ok:
        return None, response.failure_kind or "unavailable"
    return response.payload, None


def _download_retry_delay(bot: SweeperContext, retry_attempt: int) -> float:
    base = float(bot.lock_retry_base_seconds())
    return retrying.bounded_exponential_delay(base, retry_attempt, jitter=bot.jitter)


def _sleep(bot: SweeperContext, seconds: float) -> None:
    bot.sleeper.sleep(seconds)


_fetch_workflow_runs_for_file = observer_correlation.fetch_workflow_runs_for_file
_fetch_run_detail = observer_correlation.fetch_run_detail
inspect_run_artifact_payloads = observer_correlation.inspect_run_artifact_payloads


def _complete_surface_scan(bot, review_data: dict, surface: str, discovered: list[dict]) -> None:
    observer_correlation.complete_surface_scan(
        bot,
        review_data,
        surface,
        discovered,
    )


def _diagnose_deferred_event(
    bot,
    review_data: dict,
    *,
    source_event_key: str,
    source_event_name: str,
    source_event_action: str,
    source_created_at: str,
    issue_number: int,
    workflow_file: str,
    source_event_kind: str,
    workflow_runs: list[dict] | None,
    source_evidence: dict | None = None,
) -> None:
    existing_gap = gap_bookkeeping.get_deferred_gap(review_data, source_event_key)
    run_correlation = deferred_gap_diagnosis.correlate_candidate_observer_runs(
        source_event_key,
        source_event_kind=source_event_kind,
        source_event_created_at=source_created_at,
        pr_number=issue_number,
        workflow_file=workflow_file,
        workflow_runs=workflow_runs,
        github_repository=_github_repository(bot),
    )
    run_correlation["later_recheck_complete"] = bool(existing_gap.get("full_scan_complete"))
    artifact_correlation = None
    run_detail = None
    if run_correlation.get("status") == "candidate_runs_found":
        artifact_correlation = inspect_run_artifact_payloads(
            bot,
            run_correlation.get("candidate_runs", []),
            source_event_key,
            pr_number=issue_number,
            source_event_kind=source_event_kind,
        )
        exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
        if isinstance(exact_run_id, int):
            run_correlation["correlated_run"] = exact_run_id
            run_correlation["correlated_run_found"] = True
        run_detail = _maybe_fetch_single_candidate_run_detail(bot, run_correlation, artifact_correlation)
    reason, diagnostic_reason = deferred_gap_diagnosis.evaluate_deferred_gap_state(
        {
            **existing_gap,
            "source_event_created_at": source_created_at,
        },
        run_correlation,
        run_detail,
        artifact_correlation,
        runbook_signature=_approval_pending_signature_from_runbook(),
    )
    _record_gap_diagnostics(
        bot,
        review_data,
        source_event_key,
        source_event_name=source_event_name,
        source_event_action=source_event_action,
        issue_number=issue_number,
        source_created_at=source_created_at,
        workflow_file=workflow_file,
        run_correlation=run_correlation,
        run_detail=run_detail,
        artifact_correlation=artifact_correlation,
        reason=reason,
        diagnostic_reason=diagnostic_reason,
        source_evidence=source_evidence,
    )


def _list_issue_comments_paginated(bot, issue_number: int) -> tuple[list[dict] | None, bool]:
    comments: list[dict] = []
    page = 1
    while True:
        response, _ = _read_api_payload(bot, f"issues/{issue_number}/comments?per_page=100&page={page}")
        if response is None:
            return None, False
        if not isinstance(response, list):
            return None, False
        comments.extend([comment for comment in response if isinstance(comment, dict)])
        if len(response) < 100:
            return comments, True
        page += 1


def _list_review_comments_paginated(bot, issue_number: int) -> tuple[list[dict] | None, bool]:
    comments: list[dict] = []
    page = 1
    while True:
        response, _ = _read_api_payload(bot, f"pulls/{issue_number}/comments?per_page=100&page={page}")
        if response is None:
            return None, False
        if not isinstance(response, list):
            return None, False
        comments.extend([comment for comment in response if isinstance(comment, dict)])
        if len(response) < 100:
            return comments, True
        page += 1


def _list_timeline_events_paginated(bot, issue_number: int) -> tuple[list[dict] | None, bool]:
    events: list[dict] = []
    page = 1
    while True:
        response, _ = _read_api_payload(bot, f"issues/{issue_number}/timeline?per_page=100&page={page}")
        if response is None:
            return None, False
        if not isinstance(response, list):
            return None, False
        events.extend([event for event in response if isinstance(event, dict)])
        if len(response) < 100:
            return events, True
        page += 1


def _is_automation_comment(comment: dict) -> bool:
    user = comment.get("user") if isinstance(comment, dict) else None
    login = user.get("login") if isinstance(user, dict) else None
    user_type = user.get("type") if isinstance(user, dict) else None
    if isinstance(login, str):
        lowered = login.lower()
        if lowered == "github-actions[bot]" or lowered == "guidelines-bot" or lowered.endswith("[bot]"):
            return True
    if isinstance(user_type, str) and user_type.lower() == "bot":
        return True
    if comment.get("performed_via_github_app"):
        return True
    return False


def _performed_via_github_app_truth(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        app_id = value.get("id")
        if app_id is None or not str(app_id).strip():
            return None
        try:
            return int(app_id) > 0
        except (TypeError, ValueError):
            return None
    return None


def _source_actor_fields_from_user(user: object) -> dict:
    if not isinstance(user, dict):
        return {}
    fields = {}
    login = user.get("login")
    if isinstance(login, str) and login.strip():
        fields["source_actor_login"] = login.strip()
    actor_id = user.get("id")
    if actor_id is not None:
        fields["source_actor_id"] = actor_id
    user_type = user.get("type")
    if isinstance(user_type, str) and user_type.strip():
        fields["source_actor_user_type"] = user_type.strip()
    return fields


def _comment_source_evidence(comment: object) -> dict:
    if not isinstance(comment, dict):
        return {}
    fields = _source_actor_fields_from_user(comment.get("user"))
    comment_id = comment.get("id")
    if comment_id is not None:
        fields["source_comment_id"] = comment_id
    review_id = comment.get("pull_request_review_id")
    if review_id is not None:
        fields["source_review_id"] = review_id
    commit_id = comment.get("commit_id") or comment.get("original_commit_id")
    if isinstance(commit_id, str) and commit_id.strip():
        fields["source_commit_id"] = commit_id.strip()
    sender = comment.get("sender")
    sender_type = sender.get("type") if isinstance(sender, dict) else None
    if isinstance(sender_type, str) and sender_type.strip():
        fields["source_actor_sender_type"] = sender_type.strip()
    installation = comment.get("installation")
    installation_id = installation.get("id") if isinstance(installation, dict) else None
    if installation_id is not None and str(installation_id).strip():
        fields["source_actor_installation_id"] = str(installation_id).strip()
    performed_via_app = _performed_via_github_app_truth(comment.get("performed_via_github_app"))
    if performed_via_app is not None:
        fields["source_actor_performed_via_github_app"] = performed_via_app
    return fields


def _review_source_evidence(review: object) -> dict:
    if not isinstance(review, dict):
        return {}
    fields = _source_actor_fields_from_user(review.get("user"))
    review_id = review.get("id")
    if review_id is not None:
        fields["source_review_id"] = review_id
    commit_id = review.get("commit_id")
    if isinstance(commit_id, str) and commit_id.strip():
        fields["source_commit_id"] = commit_id.strip()
    state = review.get("state")
    if isinstance(state, str) and state.strip():
        fields["source_review_state"] = state.strip()
    return fields


def _fetch_live_issue_comment(bot, comment_id: str) -> dict | None:
    if not comment_id.isdigit():
        return None
    response, _ = _read_api_payload(bot, f"issues/comments/{comment_id}")
    return response if isinstance(response, dict) else None


def _clear_bot_authored_comment_false_positive(bot, review_data: dict, source_event_key: str) -> bool:
    if not source_event_key.startswith("issue_comment:"):
        return False
    comment_id = source_event_key.split(":", 1)[1]
    live_comment = _fetch_live_issue_comment(bot, comment_id)
    if not isinstance(live_comment, dict) or not _is_automation_comment(live_comment):
        return False
    return gap_bookkeeping.clear_automation_comment_false_positive(review_data, source_event_key)


def _maybe_fetch_single_candidate_run_detail(bot, run_correlation: dict, artifact_correlation: dict | None) -> dict | None:
    correlated_run = run_correlation.get("correlated_run")
    if isinstance(correlated_run, int):
        return _fetch_run_detail(bot, correlated_run)
    candidate_run_ids = run_correlation.get("candidate_run_ids")
    if not isinstance(candidate_run_ids, list):
        return None
    candidate_ints = [run_id for run_id in candidate_run_ids if isinstance(run_id, int)]
    if len(candidate_ints) != 1:
        return None
    if isinstance(artifact_correlation, dict) and artifact_correlation.get("status") == "observer_state_unknown":
        return None
    run_id = candidate_ints[0]
    run_correlation["correlated_run"] = run_id
    run_correlation["correlated_run_found"] = True
    return _fetch_run_detail(bot, run_id)


def _discover_visible_comment_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    floor = gap_bookkeeping.begin_observer_surface_scan(bot, review_data, "comments", now=_now())
    comments, complete = _list_issue_comments_paginated(bot, issue_number)
    if comments is None:
        return None, False
    discovered: list[dict] = []
    for comment in comments:
        if _is_automation_comment(comment):
            continue
        comment_id = comment.get("id")
        created_at = comment.get("created_at")
        if not isinstance(comment_id, int) or not isinstance(created_at, str):
            continue
        created_dt = parse_timestamp(created_at)
        if created_dt is None or created_dt < floor:
            continue
        discovered.append(
            {
                "source_event_key": f"issue_comment:{comment_id}",
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_created_at": created_at,
                "object_id": str(comment_id),
                "surface": "comments",
                "comment": comment,
            }
        )
    return discovered, complete


def _discover_visible_review_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    floor = gap_bookkeeping.begin_observer_surface_scan(bot, review_data, "reviews_submitted", now=_now())
    reviews = bot.github.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None, False
    discovered: list[dict] = []
    for review in reviews:
        review_id = review.get("id") if isinstance(review, dict) else None
        submitted_at = review.get("submitted_at") if isinstance(review, dict) else None
        state = str(review.get("state", "")).strip().upper() if isinstance(review, dict) else ""
        if not isinstance(review_id, int) or not isinstance(submitted_at, str):
            continue
        if state == "DISMISSED":
            continue
        submitted_dt = parse_timestamp(submitted_at)
        if submitted_dt is None or submitted_dt < floor:
            continue
        discovered.append(
            {
                "source_event_key": f"pull_request_review:{review_id}",
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_created_at": submitted_at,
                "object_id": str(review_id),
                "surface": "reviews_submitted",
                "review": review,
            }
        )
    return discovered, True


def _discover_visible_review_comment_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    floor = gap_bookkeeping.begin_observer_surface_scan(bot, review_data, "review_comments", now=_now())
    comments, complete = _list_review_comments_paginated(bot, issue_number)
    if comments is None:
        return None, False
    discovered: list[dict] = []
    for comment in comments:
        if not isinstance(comment, dict) or _is_automation_comment(comment):
            continue
        comment_id = comment.get("id")
        created_at = comment.get("created_at")
        if not isinstance(comment_id, int) or not isinstance(created_at, str):
            continue
        created_dt = parse_timestamp(created_at)
        if created_dt is None or created_dt < floor:
            continue
        discovered.append(
            {
                "source_event_key": f"pull_request_review_comment:{comment_id}",
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_created_at": created_at,
                "object_id": str(comment_id),
                "surface": "review_comments",
                "comment": comment,
            }
        )
    return discovered, complete


def _discover_visible_review_dismissal_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    floor = gap_bookkeeping.begin_observer_surface_scan(bot, review_data, "reviews_dismissed", now=_now())
    timeline_events, complete = _list_timeline_events_paginated(bot, issue_number)
    if timeline_events is None:
        return None, False
    discovered: list[dict] = []
    for event in timeline_events:
        if event.get("event") != "review_dismissed":
            continue
        dismissed_review = event.get("dismissed_review")
        review_id = dismissed_review.get("review_id") if isinstance(dismissed_review, dict) else None
        dismissed_at = event.get("created_at")
        if not isinstance(review_id, int) or not isinstance(dismissed_at, str):
            continue
        dismissed_dt = parse_timestamp(dismissed_at)
        if dismissed_dt is None or dismissed_dt < floor:
            continue
        discovered.append(
            {
                "source_event_key": f"pull_request_review_dismissed:{review_id}",
                "source_event_name": "pull_request_review",
                "source_event_action": "dismissed",
                "source_created_at": dismissed_at,
                "object_id": str(review_id),
                "surface": "reviews_dismissed",
            }
        )
    return discovered, complete


def _record_gap_diagnostics(
    bot,
    review_data: dict,
    source_event_key: str,
    *,
    source_event_name: str,
    source_event_action: str,
    issue_number: int,
    source_created_at: str,
    workflow_file: str,
    run_correlation: dict,
    run_detail: dict | None,
    artifact_correlation: dict | None,
    reason: str,
    diagnostic_reason: str,
    source_evidence: dict | None = None,
) -> None:
    payload = {
        **(source_evidence or {}),
        "source_event_key": source_event_key,
        "source_event_name": source_event_name,
        "source_event_action": source_event_action,
        "pr_number": issue_number,
        "source_created_at": source_created_at,
        "source_workflow_file": workflow_file,
        "source_run_id": run_correlation.get("correlated_run"),
        "source_run_attempt": run_detail.get("run_attempt") if isinstance(run_detail, dict) else None,
    }
    gap_bookkeeping.record_deferred_gap_diagnostic(
        bot,
        review_data,
        payload,
        reason,
        f"Trusted sweeper diagnostics for {source_event_key}: {diagnostic_reason}. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
    )
    gap_fields = {
        "full_scan_complete": bool(run_correlation.get("full_scan_complete")),
        "later_recheck_complete": bool(run_correlation.get("later_recheck_complete")),
        "correlated_run_found": bool(run_correlation.get("correlated_run")),
    }
    raw_candidate_run_ids = run_correlation.get("candidate_run_ids")
    if isinstance(raw_candidate_run_ids, list):
        gap_fields["candidate_run_ids"] = raw_candidate_run_ids
    if isinstance(run_detail, dict):
        gap_fields["run_created_at"] = run_detail.get("created_at")
    if isinstance(artifact_correlation, dict):
        prior_visibility = artifact_correlation.get("prior_visibility", {}).get(run_correlation.get("correlated_run"), {})
        if isinstance(prior_visibility, dict):
            gap_fields.update(prior_visibility)
    gap_bookkeeping.update_deferred_gap_fields(review_data, source_event_key, gap_fields)


def _should_skip_discovered_key(bot, review_data: dict, source_event_key: str, channels: tuple[str, ...]) -> bool:
    if gap_bookkeeping.was_reconciled_source_event(review_data, source_event_key):
        return True
    if source_event_key in gap_bookkeeping.list_deferred_gap_keys(review_data):
        if gap_bookkeeping.get_deferred_gap_reason(review_data, source_event_key) in {
            "awaiting_observer_run",
            "awaiting_observer_approval",
            "observer_in_progress",
            "observer_failed",
            "observer_cancelled",
            "observer_run_missing",
            "observer_state_unknown",
            "artifact_missing",
            "artifact_invalid",
            "artifact_expired",
            "reconcile_failed_closed",
        }:
            return False
    return any(semantic_key_seen(review_data, channel, source_event_key) for channel in channels)


def sweep_deferred_gaps(bot, state: dict) -> bool:
    changed = False
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        issue_number = int(issue_key)
        pull_request, _ = _read_api_payload(bot, f"pulls/{issue_number}")
        if not isinstance(pull_request, dict) or str(pull_request.get("state", "")).lower() != "open":
            continue
        for source_event_key in gap_bookkeeping.list_deferred_gap_keys(review_data):
            if _clear_bot_authored_comment_false_positive(bot, review_data, source_event_key):
                changed = True
        discovered_comments, comments_complete = _discover_visible_comment_events(bot, issue_number, review_data)
        if comments_complete and isinstance(discovered_comments, list):
            for discovered in discovered_comments:
                source_event_key = discovered["source_event_key"]
                created_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_comment", "contributor_comment")):
                    continue
                workflow_file = ".github/workflows/reviewer-bot-pr-comment-router.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "issue_comment")
                _diagnose_deferred_event(
                    bot,
                    review_data,
                    source_event_key=source_event_key,
                    source_event_name="issue_comment",
                    source_event_action="created",
                    issue_number=issue_number,
                    source_created_at=created_at,
                    workflow_file=workflow_file,
                    source_event_kind="issue_comment:created",
                    workflow_runs=workflow_runs,
                    source_evidence=_comment_source_evidence(discovered.get("comment")),
                )
                changed = True
            _complete_surface_scan(bot, review_data, "comments", discovered_comments)
        discovered_reviews, reviews_complete = _discover_visible_review_events(bot, issue_number, review_data)
        if reviews_complete and isinstance(discovered_reviews, list):
            for discovered in discovered_reviews:
                source_event_key = discovered["source_event_key"]
                submitted_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_review",)):
                    continue
                existing_gap = gap_bookkeeping.get_deferred_gap(review_data, source_event_key)
                workflow_file = ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review")
                run_correlation = deferred_gap_diagnosis.correlate_candidate_observer_runs(
                    source_event_key,
                    source_event_kind="pull_request_review:submitted",
                    source_event_created_at=submitted_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
                    github_repository=_github_repository(bot),
                )
                run_correlation["later_recheck_complete"] = bool(existing_gap.get("full_scan_complete"))
                artifact_correlation = None
                run_detail = None
                if run_correlation.get("status") == "candidate_runs_found":
                    artifact_correlation = inspect_run_artifact_payloads(
                        bot,
                        run_correlation.get("candidate_runs", []),
                        source_event_key,
                        pr_number=issue_number,
                        source_event_kind="pull_request_review:submitted",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                    run_detail = _maybe_fetch_single_candidate_run_detail(bot, run_correlation, artifact_correlation)
                review_payload = discovered.get("review") if isinstance(discovered.get("review"), dict) else None
                artifact_status = artifact_correlation.get("status") if isinstance(artifact_correlation, dict) else None
                visible_review_diagnostic = deferred_gap_diagnosis.describe_review_submission_gap_diagnostic(
                    review_data,
                    review_payload,
                    source_event_key,
                    artifact_status=artifact_status,
                    current_cycle_boundary=get_current_cycle_boundary(bot, review_data),
                )
                reason, diagnostic_reason = deferred_gap_diagnosis.evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": submitted_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                    runbook_signature=_approval_pending_signature_from_runbook(),
                )
                if visible_review_diagnostic is not None:
                    diagnostic_reason = f"{diagnostic_reason}; {visible_review_diagnostic['category']}"
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="pull_request_review",
                    source_event_action="submitted",
                    issue_number=issue_number,
                    source_created_at=submitted_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                    source_evidence=_review_source_evidence(review_payload),
                )
                if visible_review_diagnostic is not None:
                    gap_bookkeeping.update_deferred_gap_fields(
                        review_data,
                        source_event_key,
                        {"visible_review_diagnostic": visible_review_diagnostic},
                    )
                changed = True
            if discovered_reviews:
                _complete_surface_scan(bot, review_data, "reviews_submitted", discovered_reviews)
            else:
                gap_bookkeeping.record_observer_watermark_empty_scan(bot, review_data, "reviews_submitted")
        discovered_review_comments, review_comments_complete = _discover_visible_review_comment_events(bot, issue_number, review_data)
        if review_comments_complete and isinstance(discovered_review_comments, list):
            for discovered in discovered_review_comments:
                source_event_key = discovered["source_event_key"]
                created_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_comment", "contributor_comment")):
                    continue
                workflow_file = ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review_comment")
                _diagnose_deferred_event(
                    bot,
                    review_data,
                    source_event_key=source_event_key,
                    source_event_name="pull_request_review_comment",
                    source_event_action="created",
                    issue_number=issue_number,
                    source_created_at=created_at,
                    workflow_file=workflow_file,
                    source_event_kind="pull_request_review_comment:created",
                    workflow_runs=workflow_runs,
                    source_evidence=_comment_source_evidence(discovered.get("comment")),
                )
                changed = True
            _complete_surface_scan(bot, review_data, "review_comments", discovered_review_comments)
        discovered_dismissals, dismissals_complete = _discover_visible_review_dismissal_events(bot, issue_number, review_data)
        if dismissals_complete and isinstance(discovered_dismissals, list):
            for discovered in discovered_dismissals:
                source_event_key = discovered["source_event_key"]
                dismissed_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("review_dismissal",)):
                    continue
                workflow_file = ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review")
                _diagnose_deferred_event(
                    bot,
                    review_data,
                    source_event_key=source_event_key,
                    source_event_name="pull_request_review",
                    source_event_action="dismissed",
                    issue_number=issue_number,
                    source_created_at=dismissed_at,
                    workflow_file=workflow_file,
                    source_event_kind="pull_request_review:dismissed",
                    workflow_runs=workflow_runs,
                )
                changed = True
            _complete_surface_scan(bot, review_data, "reviews_dismissed", discovered_dismissals)
    return changed
