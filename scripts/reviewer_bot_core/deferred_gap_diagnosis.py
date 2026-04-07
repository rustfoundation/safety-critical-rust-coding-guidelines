"""Deferred gap diagnosis and narrow visible-review recommendation helpers.

This module owns diagnosis vocabulary selection and the current narrow visible-review
repair recommendation seam. It does not fetch evidence or mutate review state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
    return bool(
        gap.get("full_scan_complete")
        and gap.get("later_recheck_complete")
        and not gap.get("correlated_run_found")
        and not gap.get("approval_pending_evidence_retained")
    )


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
    source_event_key: str,
    *,
    source_event_kind: str,
    source_event_created_at: str,
    pr_number: int,
    workflow_file: str,
    workflow_runs: list[dict] | None,
    github_repository: str,
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
            if isinstance(full_name, str) and full_name != github_repository:
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


def evaluate_deferred_gap_state(
    existing_gap: dict,
    run_correlation: dict,
    run_detail: dict | None,
    artifact_correlation: dict | None,
    *,
    runbook_signature: dict | None = None,
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
    run_state = observer_run_reason_from_details(run_detail, runbook_signature)
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


def recommend_visible_review_repair(
    review_data: dict,
    review: dict,
    source_event_key: str,
    *,
    current_cycle_boundary,
) -> tuple[str, str, str] | None:
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
    submitted_dt = parse_timestamp(submitted_at)
    if current_cycle_boundary is None or submitted_dt is None or submitted_dt < current_cycle_boundary:
        return None
    if source_event_key != f"pull_request_review:{review_id}":
        return None
    return author, submitted_at, commit_id


def recommend_review_submission_gap_repair(
    review_data: dict,
    review: dict | None,
    source_event_key: str,
    *,
    artifact_status: str | None,
    current_cycle_boundary,
) -> dict[str, object] | None:
    if review is None or artifact_status == "exact_artifact_match":
        return None
    repair = recommend_visible_review_repair(
        review_data,
        review,
        source_event_key,
        current_cycle_boundary=current_cycle_boundary,
    )
    if repair is None:
        return None
    author, submitted_at, commit_id = repair
    return {
        "category": "review_submission_repair",
        "payload": {
            "author": author,
            "submitted_at": submitted_at,
            "commit_id": commit_id,
        },
    }
