"""Deferred evidence sweeper, run correlation, and artifact correlation helpers."""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from . import retrying
from .context import SweeperContext
from .reconcile import (
    _artifact_expected_name,
    _artifact_expected_payload_name,
    _clear_source_event_key,
    _mark_reconciled_source_event,
    _update_deferred_gap,
    _was_reconciled_source_event,
)
from .review_state import (
    accept_reviewer_review_from_live_review,
    get_current_cycle_boundary,
    record_reviewer_activity,
    refresh_reviewer_review_from_live_preferred_review,
    semantic_key_seen,
)
from .reviews import rebuild_pr_approval_state


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _retention_days(bot: SweeperContext) -> int:
    return int(bot.get_config_value("DEFERRED_ARTIFACT_RETENTION_DAYS", "7") or 7)


def _github_repository(bot: SweeperContext) -> str:
    return bot.get_config_value("GITHUB_REPOSITORY", "")


def _approval_pending_signature_from_runbook() -> dict | None:
    return None


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
    base = float(getattr(bot, "LOCK_RETRY_BASE_SECONDS", 2.0))

    class _BotJitter:
        def uniform(self, lower: float, upper: float) -> float:
            jitter = getattr(bot, "jitter", None)
            if jitter is not None and hasattr(jitter, "uniform"):
                return jitter.uniform(lower, upper)
            return __import__("random").uniform(lower, upper)

    return retrying.bounded_exponential_delay(base, retry_attempt, jitter=_BotJitter())


def observer_run_reason_from_details(run_details: dict, runbook_signature: dict | None) -> str:
    status = str(run_details.get("status", "")).strip()
    conclusion = run_details.get("conclusion")
    if runbook_signature and all(run_details.get(key) == value for key, value in runbook_signature.items()):
        return "awaiting_observer_approval"
    if status in {"queued", "in_progress"}:
        return "observer_in_progress"
    if status == "completed":
        if conclusion == "success":
            return "completed_success"
        if conclusion in {"failure", "timed_out", "action_required", "stale"}:
            return "observer_failed"
        if conclusion == "cancelled":
            return "observer_cancelled"
    return "observer_state_unknown"


def can_mark_observer_run_missing(gap: dict, now: datetime | None = None) -> bool:
    now = now or _now()
    created_at = gap.get("source_event_created_at")
    created_dt = parse_timestamp(created_at)
    if created_dt is None or now < created_dt + timedelta(hours=24):
        return False
    return bool(gap.get("full_scan_complete") and gap.get("later_recheck_complete") and not gap.get("correlated_run_found") and not gap.get("approval_pending_evidence_retained"))


def classify_artifact_gap_reason(gap: dict, now: datetime | None = None, *, retention_days: int = 7) -> str:
    now = now or _now()
    run_created_at = parse_timestamp(gap.get("run_created_at"))
    if gap.get("artifact_seen_at") or gap.get("artifact_last_downloadable_at"):
        return "artifact_expired"
    if run_created_at is not None and gap.get("retention_window_documented") and now >= run_created_at + timedelta(days=retention_days):
        return "artifact_expired"
    if gap.get("artifact_inspection_complete"):
        return "artifact_missing"
    return "observer_state_unknown"


def correlate_candidate_observer_runs(
    bot: SweeperContext,
    source_event_key: str,
    *,
    source_event_kind: str,
    source_event_created_at: str,
    pr_number: int,
    workflow_file: str,
    workflow_runs: list[dict] | None,
) -> dict:
    created_at = parse_timestamp(source_event_created_at)
    if created_at is None:
        return {
            "status": "observer_state_unknown",
            "reason": "invalid_source_event_created_at",
            "candidate_run_ids": [],
            "full_scan_complete": False,
            "later_recheck_complete": False,
            "correlated_run": None,
        }
    if workflow_runs is None:
        return {
            "status": "observer_state_unknown",
            "reason": "workflow_run_scan_unavailable",
            "candidate_run_ids": [],
            "full_scan_complete": False,
            "later_recheck_complete": False,
            "correlated_run": None,
        }
    expected_event_map = {
        "issue_comment:created": "issue_comment",
        "pull_request_review:submitted": "pull_request_review",
        "pull_request_review:dismissed": "pull_request_review",
        "pull_request_review_comment:created": "pull_request_review_comment",
    }
    expected_event = expected_event_map.get(source_event_kind)
    if expected_event is None:
        return {
            "status": "observer_state_unknown",
            "reason": "unsupported_source_event_kind",
            "candidate_run_ids": [],
            "full_scan_complete": False,
            "later_recheck_complete": False,
            "correlated_run": None,
        }
    window_start = created_at - timedelta(minutes=2)
    window_end = created_at + timedelta(minutes=30)
    candidates: list[dict] = []
    for run in workflow_runs:
        if not isinstance(run, dict):
            continue
        if str(run.get("event", "")) != expected_event:
            continue
        created = parse_timestamp(run.get("created_at"))
        if created is None or created < window_start or created > window_end:
            continue
        if str(run.get("path", "")) != workflow_file:
            continue
        repo = run.get("repository")
        if isinstance(repo, dict):
            full_name = repo.get("full_name")
            if isinstance(full_name, str) and full_name != _github_repository(bot):
                continue
        prs = run.get("pull_requests")
        if isinstance(prs, list) and prs:
            if not any(isinstance(pr, dict) and pr.get("number") == pr_number for pr in prs):
                continue
        candidates.append(run)
    candidate_run_ids = [run.get("id") for run in candidates if isinstance(run.get("id"), int)]
    return {
        "status": "candidate_runs_found" if candidates else "no_candidate_runs",
        "reason": None,
        "candidate_runs": candidates,
        "candidate_run_ids": candidate_run_ids,
        "full_scan_complete": True,
        "later_recheck_complete": False,
        "correlated_run": None,
    }


def correlate_run_artifacts_exact(
    payloads_by_run: dict[int, list[dict]] | None,
    source_event_key: str,
    *,
    pr_number: int,
) -> dict:
    if payloads_by_run is None:
        return {"status": "observer_state_unknown", "reason": "artifact_scan_unavailable", "correlated_run": None}
    matches: list[tuple[int, dict]] = []
    candidate_run_ids: list[int] = []
    for run_id, payloads in payloads_by_run.items():
        if not isinstance(run_id, int):
            continue
        candidate_run_ids.append(run_id)
        latest_by_attempt: dict[int, dict] = {}
        for artifact_payload in payloads:
            if not isinstance(artifact_payload, dict):
                continue
            attempt = artifact_payload.get("source_run_attempt")
            if not isinstance(attempt, int):
                continue
            previous = latest_by_attempt.get(attempt)
            if previous is None or artifact_payload.get("source_event_key") == source_event_key:
                latest_by_attempt[attempt] = artifact_payload
        for artifact_payload in latest_by_attempt.values():
            if artifact_payload.get("source_event_key") != source_event_key:
                continue
            if artifact_payload.get("source_run_id") != run_id:
                continue
            if artifact_payload.get("pr_number") != pr_number:
                continue
            matches.append((run_id, artifact_payload))
    if not matches:
        return {
            "status": "no_exact_artifact_match",
            "reason": "no_exact_source_event_key_match",
            "correlated_run": None,
            "candidate_run_ids": sorted(candidate_run_ids),
        }
    distinct_run_ids = sorted({run_id for run_id, _ in matches})
    if len(distinct_run_ids) > 1:
        return {
            "status": "observer_state_unknown",
            "reason": "ambiguous_exact_artifact_matches",
            "correlated_run": None,
            "candidate_run_ids": distinct_run_ids,
        }
    run_id, matched_payload = matches[-1]
    return {
        "status": "exact_artifact_match",
        "reason": None,
        "correlated_run": run_id,
        "artifact_payload": matched_payload,
        "candidate_run_ids": distinct_run_ids,
    }


def _fetch_workflow_runs_for_file(bot: SweeperContext, workflow_file: str, event_name: str) -> list[dict] | None:
    runs: list[dict] = []
    page = 1
    encoded_workflow = quote(workflow_file, safe="")
    while True:
        response, _ = _read_api_payload(
            bot,
            f"actions/workflows/{encoded_workflow}/runs?event={quote(event_name, safe='')}&per_page=100&page={page}",
        )
        if response is None:
            return None
        workflow_runs = response.get("workflow_runs") if isinstance(response, dict) else None
        if not isinstance(workflow_runs, list):
            return None
        runs.extend([run for run in workflow_runs if isinstance(run, dict)])
        if len(workflow_runs) < 100:
            return runs
        page += 1


def _fetch_run_detail(bot: SweeperContext, run_id: int) -> dict | None:
    response, _ = _read_api_payload(bot, f"actions/runs/{run_id}")
    if isinstance(response, dict):
        return response
    return None


def _list_run_artifacts(bot: SweeperContext, run_id: int) -> list[dict] | None:
    artifacts: list[dict] = []
    page = 1
    while True:
        response, _ = _read_api_payload(bot, f"actions/runs/{run_id}/artifacts?per_page=100&page={page}")
        if response is None:
            return None
        page_artifacts = response.get("artifacts") if isinstance(response, dict) else None
        if not isinstance(page_artifacts, list):
            return None
        artifacts.extend([artifact for artifact in page_artifacts if isinstance(artifact, dict)])
        if len(page_artifacts) < 100:
            return artifacts
        page += 1


def _download_artifact_payload(bot: SweeperContext, artifact: dict, expected_payload_name: str) -> tuple[str, dict | None]:
    if artifact.get("expired") is True:
        return "expired", None
    download_url = artifact.get("archive_download_url")
    if not isinstance(download_url, str) or not download_url:
        return "missing_download_url", None
    max_attempts = int(getattr(bot, "LOCK_API_RETRY_LIMIT", 5)) + 1
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = bot.artifact_download_transport.download(
                download_url,
                headers={
                    "Authorization": f"Bearer {bot.get_github_token()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except Exception:
            if attempt < max_attempts:
                time.sleep(_download_retry_delay(bot, attempt))
                continue
            return "download_unavailable", None
        if retrying.is_retryable_status(response.status_code):
            if attempt < max_attempts:
                time.sleep(_download_retry_delay(bot, attempt))
                continue
            return "download_unavailable", None
        break
    if response is None:
        return "download_unavailable", None
    if response.status_code >= 400:
        return "download_failed", None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            payload_files = [name for name in archive.namelist() if not name.endswith("/")]
            if payload_files != [expected_payload_name]:
                return "invalid_payload_layout", None
            with archive.open(expected_payload_name) as handle:
                payload = json.loads(handle.read().decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return "invalid_payload_format", None
    if not isinstance(payload, dict):
        return "invalid_payload_format", None
    return "ok", payload


def inspect_run_artifact_payloads(bot: SweeperContext, workflow_runs: list[dict], source_event_key: str, *, pr_number: int, source_event_kind: str) -> dict:
    payloads_by_run: dict[int, list[dict]] = {}
    prior_visibility: dict[int, dict[str, str]] = {}
    artifact_scan_outcomes: dict[int, str] = {}
    event_name, event_action = source_event_kind.split(":", 1)
    expected_payload_name = _artifact_expected_payload_name(
        {
            "source_event_name": event_name,
            "source_event_action": event_action,
        }
    )
    for run in workflow_runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        run_attempt = run.get("run_attempt")
        if not isinstance(run_attempt, int):
            continue
        expected_name = _artifact_expected_name(
            {
                "source_event_name": event_name,
                "source_event_action": event_action,
                "source_run_id": run_id,
                "source_run_attempt": run_attempt,
            }
        )
        artifacts = _list_run_artifacts(bot, run_id)
        if artifacts is None:
            return {"status": "observer_state_unknown", "reason": "artifact_listing_unavailable", "payloads_by_run": None}
        filtered = []
        for artifact in artifacts:
            name = artifact.get("name")
            if not isinstance(name, str) or name != expected_name:
                continue
            filtered.append(artifact)
            prior_visibility[run_id] = {"artifact_seen_at": _now_iso()}
            status, payload = _download_artifact_payload(bot, artifact, expected_payload_name)
            if status == "ok" and isinstance(payload, dict):
                payloads_by_run.setdefault(run_id, []).append(payload)
                artifact_scan_outcomes[run_id] = "ok"
            elif status == "expired":
                prior_visibility[run_id]["artifact_last_downloadable_at"] = prior_visibility[run_id]["artifact_seen_at"]
                artifact_scan_outcomes[run_id] = "expired"
            else:
                artifact_scan_outcomes[run_id] = status
        if run_id not in payloads_by_run and filtered:
            payloads_by_run.setdefault(run_id, [])
    result = correlate_run_artifacts_exact(payloads_by_run, source_event_key, pr_number=pr_number)
    result["payloads_by_run"] = payloads_by_run
    result["prior_visibility"] = prior_visibility
    result["artifact_scan_outcomes"] = artifact_scan_outcomes
    return result


def evaluate_deferred_gap_state(
    existing_gap: dict,
    run_correlation: dict,
    run_detail: dict | None,
    artifact_correlation: dict | None,
) -> tuple[str, str]:
    if run_correlation.get("status") == "observer_state_unknown":
        return "observer_state_unknown", str(run_correlation.get("reason") or "run_scan_unknown")
    if run_correlation.get("status") == "no_candidate_runs":
        gap = dict(existing_gap)
        gap["full_scan_complete"] = bool(run_correlation.get("full_scan_complete"))
        gap["later_recheck_complete"] = bool(run_correlation.get("later_recheck_complete"))
        gap["correlated_run_found"] = False
        gap["approval_pending_evidence_retained"] = False
        if can_mark_observer_run_missing(gap):
            return "observer_run_missing", "negative_inference_satisfied"
        created_at = parse_timestamp(existing_gap.get("source_event_created_at"))
        if created_at is not None and _now() < created_at + timedelta(hours=24):
            return "awaiting_observer_run", "missing_run_window_open"
        return "observer_state_unknown", "missing_run_window_not_proven"
    if run_detail is None:
        return "observer_state_unknown", "run_detail_unavailable"
    run_state = observer_run_reason_from_details(run_detail, _approval_pending_signature_from_runbook())
    if run_state in {
        "awaiting_observer_approval",
        "observer_in_progress",
        "observer_failed",
        "observer_cancelled",
        "observer_state_unknown",
    }:
        return run_state, f"run_detail:{run_state}"
    if run_state != "completed_success":
        return "observer_state_unknown", "unmapped_run_state"
    if artifact_correlation is None:
        return "artifact_missing", "artifact_correlation_unavailable"
    artifact_status = artifact_correlation.get("status")
    if artifact_status == "exact_artifact_match":
        return "observer_state_unknown", "successful_artifact_present_without_reconcile_marker"
    if artifact_status == "no_exact_artifact_match":
        scan_outcomes = artifact_correlation.get("artifact_scan_outcomes")
        if isinstance(scan_outcomes, dict):
            if any(outcome == "expired" for outcome in scan_outcomes.values()):
                return "artifact_expired", "prior_visibility_or_retention_proof_required"
            if any(outcome == "download_unavailable" for outcome in scan_outcomes.values()):
                return "observer_state_unknown", "artifact_download_unavailable"
            invalid_outcomes = {"missing_download_url", "download_failed", "invalid_payload_layout", "invalid_payload_format"}
            if any(outcome in invalid_outcomes for outcome in scan_outcomes.values()):
                return "artifact_invalid", "artifact_download_or_payload_invalid"
        return "artifact_missing", str(artifact_correlation.get("reason") or "exact_artifact_missing")
    if artifact_status == "observer_state_unknown":
        return "observer_state_unknown", str(artifact_correlation.get("reason") or "artifact_ambiguity")
    return "artifact_invalid", str(artifact_correlation.get("reason") or "artifact_invalid")


def _update_observer_watermark(bot, review_data: dict, surface: str, event_time: str, event_id: str) -> None:
    watermarks = review_data.setdefault("observer_discovery_watermarks", {})
    current = watermarks.get(surface) if isinstance(watermarks.get(surface), dict) else {}
    watermarks[surface] = {
        "last_scan_started_at": current.get("last_scan_started_at") or _now_iso(),
        "last_scan_completed_at": _now_iso(),
        "last_safe_event_time": event_time,
        "last_safe_event_id": event_id,
        "lookback_seconds": bot.DEFERRED_DISCOVERY_OVERLAP_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS") else 3600,
        "bootstrap_window_seconds": bot.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS") else 604800,
        "bootstrap_completed_at": current.get("bootstrap_completed_at") or _now_iso(),
    }


def _load_surface_watermark(review_data: dict, surface: str) -> dict:
    watermarks = review_data.setdefault("observer_discovery_watermarks", {})
    current = watermarks.get(surface)
    if isinstance(current, dict):
        return current
    current = {
        "last_scan_started_at": None,
        "last_scan_completed_at": None,
        "last_safe_event_time": None,
        "last_safe_event_id": None,
        "lookback_seconds": None,
        "bootstrap_window_seconds": None,
        "bootstrap_completed_at": None,
    }
    watermarks[surface] = current
    return current


def _surface_scan_floor(bot, watermark: dict) -> datetime:
    now = _now()
    bootstrap_floor = now - timedelta(seconds=bot.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS)
    safe_time = parse_timestamp(watermark.get("last_safe_event_time"))
    if safe_time is None:
        return bootstrap_floor
    return max(bootstrap_floor, safe_time - timedelta(seconds=bot.DEFERRED_DISCOVERY_OVERLAP_SECONDS))


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


def _fetch_live_issue_comment(bot, comment_id: str) -> dict | None:
    if not comment_id.isdigit():
        return None
    response, _ = _read_api_payload(bot, f"issues/comments/{comment_id}")
    return response if isinstance(response, dict) else None


def _purge_bot_authored_comment_gap(bot, review_data: dict, source_event_key: str) -> bool:
    if not source_event_key.startswith("issue_comment:"):
        return False
    comment_id = source_event_key.split(":", 1)[1]
    live_comment = _fetch_live_issue_comment(bot, comment_id)
    if not isinstance(live_comment, dict) or not _is_automation_comment(live_comment):
        return False
    deferred_gaps = review_data.get("deferred_gaps")
    if not isinstance(deferred_gaps, dict) or source_event_key not in deferred_gaps:
        return False
    deferred_gaps.pop(source_event_key, None)
    return True


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


def _can_repair_visible_review(bot, review_data: dict, review: dict, source_event_key: str) -> tuple[str, str, str] | None:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return None
    author = review.get("user", {}).get("login") if isinstance(review, dict) else None
    commit_id = review.get("commit_id") if isinstance(review, dict) else None
    submitted_at = review.get("submitted_at") if isinstance(review, dict) else None
    review_id = review.get("id") if isinstance(review, dict) else None
    if not isinstance(author, str) or author.lower() != current_reviewer.lower():
        return None
    if not isinstance(commit_id, str) or not commit_id.strip():
        return None
    if not isinstance(submitted_at, str):
        return None
    boundary = get_current_cycle_boundary(bot, review_data)
    submitted_dt = parse_timestamp(submitted_at)
    if boundary is None or submitted_dt is None or submitted_dt < boundary:
        return None
    if source_event_key != f"pull_request_review:{review_id}":
        return None
    return author, submitted_at, commit_id


def _repair_visible_review_gap(bot, review_data: dict, issue_number: int, source_event_key: str, review: dict) -> bool:
    repair = _can_repair_visible_review(bot, review_data, review, source_event_key)
    if repair is None:
        return False
    author, submitted_at, commit_id = repair
    changed = accept_reviewer_review_from_live_review(review_data, review, actor=author)
    changed = refresh_reviewer_review_from_live_preferred_review(
        bot,
        issue_number,
        review_data,
        actor=author,
    )[0] or changed
    record_reviewer_activity(review_data, submitted_at)
    completion, _ = rebuild_pr_approval_state(bot, issue_number, review_data)
    reconciled_changed = _mark_reconciled_source_event(review_data, source_event_key)
    gap_cleared_changed = _clear_source_event_key(review_data, source_event_key)
    return changed or completion is not None or reconciled_changed or gap_cleared_changed


def _discover_visible_comment_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    watermark = _load_surface_watermark(review_data, "comments")
    watermark["last_scan_started_at"] = _now_iso()
    comments, complete = _list_issue_comments_paginated(bot, issue_number)
    if comments is None:
        return None, False
    floor = _surface_scan_floor(bot, watermark)
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
    watermark = _load_surface_watermark(review_data, "reviews_submitted")
    watermark["last_scan_started_at"] = _now_iso()
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None, False
    floor = _surface_scan_floor(bot, watermark)
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
    watermark = _load_surface_watermark(review_data, "review_comments")
    watermark["last_scan_started_at"] = _now_iso()
    comments, _ = _read_api_payload(bot, f"pulls/{issue_number}/comments?per_page=100")
    if comments is None:
        return None, False
    if not isinstance(comments, list):
        return None, False
    floor = _surface_scan_floor(bot, watermark)
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
    return discovered, True


def _discover_visible_review_dismissal_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    watermark = _load_surface_watermark(review_data, "reviews_dismissed")
    watermark["last_scan_started_at"] = _now_iso()
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None, False
    floor = _surface_scan_floor(bot, watermark)
    discovered: list[dict] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        review_id = review.get("id")
        state = str(review.get("state", "")).strip().upper()
        dismissed_at = review.get("dismissed_at") or review.get("updated_at") or review.get("submitted_at")
        if state != "DISMISSED":
            continue
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
    return discovered, True


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
) -> None:
    _update_deferred_gap(
        bot,
        review_data,
        {
            "source_event_key": source_event_key,
            "source_event_name": source_event_name,
            "source_event_action": source_event_action,
            "pr_number": issue_number,
            "source_created_at": source_created_at,
            "source_workflow_file": workflow_file,
            "source_run_id": run_correlation.get("correlated_run"),
            "source_run_attempt": run_detail.get("run_attempt") if isinstance(run_detail, dict) else None,
            "source_artifact_name": _artifact_expected_name(
                {
                    "source_event_name": source_event_name,
                    "source_event_action": source_event_action,
                    "source_run_id": run_correlation.get("correlated_run") or 0,
                    "source_run_attempt": (run_detail or {}).get("run_attempt") or 0,
                }
            ),
        },
        reason,
        f"Trusted sweeper diagnostics for {source_event_key}: {diagnostic_reason}. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
    )
    gap = review_data["deferred_gaps"][source_event_key]
    gap["full_scan_complete"] = bool(run_correlation.get("full_scan_complete"))
    gap["later_recheck_complete"] = bool(run_correlation.get("later_recheck_complete"))
    gap["correlated_run_found"] = bool(run_correlation.get("correlated_run"))
    raw_candidate_run_ids = run_correlation.get("candidate_run_ids")
    if isinstance(raw_candidate_run_ids, list):
        gap["candidate_run_ids"] = raw_candidate_run_ids
    if isinstance(run_detail, dict):
        gap["run_created_at"] = run_detail.get("created_at")
    if isinstance(artifact_correlation, dict):
        prior_visibility = artifact_correlation.get("prior_visibility", {}).get(run_correlation.get("correlated_run"), {})
        if isinstance(prior_visibility, dict):
            gap.update(prior_visibility)


def _should_skip_discovered_key(bot, review_data: dict, source_event_key: str, channels: tuple[str, ...]) -> bool:
    if _was_reconciled_source_event(review_data, source_event_key):
        return True
    if source_event_key in review_data.get("deferred_gaps", {}):
        existing_gap = review_data["deferred_gaps"].get(source_event_key)
        if isinstance(existing_gap, dict) and existing_gap.get("reason") in {
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
        deferred_gaps = review_data.get("deferred_gaps")
        if isinstance(deferred_gaps, dict):
            for source_event_key in list(deferred_gaps):
                if _purge_bot_authored_comment_gap(bot, review_data, source_event_key):
                    changed = True
        discovered_comments, comments_complete = _discover_visible_comment_events(bot, issue_number, review_data)
        if comments_complete and isinstance(discovered_comments, list):
            for discovered in discovered_comments:
                source_event_key = discovered["source_event_key"]
                created_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_comment", "contributor_comment")):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-comment-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "issue_comment")
                run_correlation = correlate_candidate_observer_runs(
                    bot,
                    source_event_key,
                    source_event_kind="issue_comment:created",
                    source_event_created_at=created_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
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
                        source_event_kind="issue_comment:created",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                    run_detail = _maybe_fetch_single_candidate_run_detail(bot, run_correlation, artifact_correlation)
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": created_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="issue_comment",
                    source_event_action="created",
                    issue_number=issue_number,
                    source_created_at=created_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                )
                changed = True
            if discovered_comments:
                last_comment = discovered_comments[-1]
                _update_observer_watermark(bot, review_data, "comments", last_comment["source_created_at"], last_comment["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "comments")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
        discovered_reviews, reviews_complete = _discover_visible_review_events(bot, issue_number, review_data)
        if reviews_complete and isinstance(discovered_reviews, list):
            for discovered in discovered_reviews:
                source_event_key = discovered["source_event_key"]
                submitted_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_review",)):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review")
                run_correlation = correlate_candidate_observer_runs(
                    bot,
                    source_event_key,
                    source_event_kind="pull_request_review:submitted",
                    source_event_created_at=submitted_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
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
                if (
                    review_payload is not None
                    and artifact_status != "exact_artifact_match"
                    and _repair_visible_review_gap(bot, review_data, issue_number, source_event_key, review_payload)
                ):
                    changed = True
                    continue
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": submitted_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
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
                )
                changed = True
            if discovered_reviews:
                last_review = discovered_reviews[-1]
                _update_observer_watermark(bot, review_data, "reviews_submitted", last_review["source_created_at"], last_review["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "reviews_submitted")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
        discovered_review_comments, review_comments_complete = _discover_visible_review_comment_events(bot, issue_number, review_data)
        if review_comments_complete and isinstance(discovered_review_comments, list):
            for discovered in discovered_review_comments:
                source_event_key = discovered["source_event_key"]
                created_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_comment", "contributor_comment")):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review_comment")
                run_correlation = correlate_candidate_observer_runs(
                    bot,
                    source_event_key,
                    source_event_kind="pull_request_review_comment:created",
                    source_event_created_at=created_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
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
                        source_event_kind="pull_request_review_comment:created",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                    run_detail = _maybe_fetch_single_candidate_run_detail(bot, run_correlation, artifact_correlation)
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": created_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="pull_request_review_comment",
                    source_event_action="created",
                    issue_number=issue_number,
                    source_created_at=created_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                )
                changed = True
            if discovered_review_comments:
                last_comment = discovered_review_comments[-1]
                _update_observer_watermark(bot, review_data, "review_comments", last_comment["source_created_at"], last_comment["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "review_comments")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
        discovered_dismissals, dismissals_complete = _discover_visible_review_dismissal_events(bot, issue_number, review_data)
        if dismissals_complete and isinstance(discovered_dismissals, list):
            for discovered in discovered_dismissals:
                source_event_key = discovered["source_event_key"]
                dismissed_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("review_dismissal",)):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review")
                run_correlation = correlate_candidate_observer_runs(
                    bot,
                    source_event_key,
                    source_event_kind="pull_request_review:dismissed",
                    source_event_created_at=dismissed_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
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
                        source_event_kind="pull_request_review:dismissed",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                        run_detail = _fetch_run_detail(bot, exact_run_id)
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": dismissed_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="pull_request_review",
                    source_event_action="dismissed",
                    issue_number=issue_number,
                    source_created_at=dismissed_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                )
                changed = True
            if discovered_dismissals:
                last_dismissal = discovered_dismissals[-1]
                _update_observer_watermark(bot, review_data, "reviews_dismissed", last_dismissal["source_created_at"], last_dismissal["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "reviews_dismissed")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
    return changed
