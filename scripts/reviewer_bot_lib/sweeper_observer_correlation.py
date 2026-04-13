"""Observer correlation helpers for reviewer-bot sweeper."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from urllib.parse import quote

from scripts.reviewer_bot_core import deferred_gap_diagnosis

from . import deferred_gap_bookkeeping as gap_bookkeeping
from . import retrying
from .reconcile_payloads import artifact_expected_name, artifact_expected_payload_name


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def _read_api_payload(bot, endpoint: str) -> tuple[Any | None, str | None]:
    try:
        response = bot.github_api_request("GET", endpoint, retry_policy="idempotent_read", suppress_error_log=True)
    except SystemExit:
        payload = bot.github_api("GET", endpoint)
        return payload, None if payload is not None else "unavailable"
    if not response.ok:
        return None, response.failure_kind or "unavailable"
    return response.payload, None


def _download_retry_delay(bot, retry_attempt: int) -> float:
    return retrying.bounded_exponential_delay(float(bot.lock_retry_base_seconds()), retry_attempt, jitter=bot.jitter)


def _sleep(bot, seconds: float) -> None:
    bot.sleeper.sleep(seconds)


def fetch_workflow_runs_for_file(bot, workflow_file: str, event_name: str) -> list[dict] | None:
    runs: list[dict] = []
    page = 1
    encoded_workflow = quote(workflow_file, safe="")
    while True:
        response, _ = _read_api_payload(bot, f"actions/workflows/{encoded_workflow}/runs?event={quote(event_name, safe='')}&per_page=100&page={page}")
        if response is None:
            return None
        workflow_runs = response.get("workflow_runs") if isinstance(response, dict) else None
        if not isinstance(workflow_runs, list):
            return None
        runs.extend([run for run in workflow_runs if isinstance(run, dict)])
        if len(workflow_runs) < 100:
            return runs
        page += 1


def fetch_run_detail(bot, run_id: int) -> dict | None:
    response, _ = _read_api_payload(bot, f"actions/runs/{run_id}")
    if isinstance(response, dict):
        return response
    return None


def _list_run_artifacts(bot, run_id: int) -> list[dict] | None:
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


def _matching_payload(payload: dict, *, run_id: int, run_attempt: int, event_name: str, event_action: str, source_event_key: str, pr_number: int) -> bool:
    return (
        payload.get("source_run_id") == run_id
        and payload.get("source_run_attempt") == run_attempt
        and payload.get("source_event_name") == event_name
        and payload.get("source_event_action") == event_action
        and payload.get("source_event_key") == source_event_key
        and payload.get("pr_number") == pr_number
    )


def _download_artifact_payloads(bot, artifact: dict) -> tuple[str, list[dict] | None]:
    if artifact.get("expired") is True:
        return "expired", None
    download_url = artifact.get("archive_download_url")
    if not isinstance(download_url, str) or not download_url:
        return "missing_download_url", None
    max_attempts = int(bot.lock_api_retry_limit()) + 1
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = bot.artifact_download_transport.download(download_url, headers={"Authorization": f"Bearer {bot.get_github_token()}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        except Exception:
            if attempt < max_attempts:
                _sleep(bot, _download_retry_delay(bot, attempt))
                continue
            return "download_unavailable", None
        if retrying.is_retryable_status(response.status_code):
            if attempt < max_attempts:
                _sleep(bot, _download_retry_delay(bot, attempt))
                continue
            return "download_unavailable", None
        break
    if response is None:
        return "download_unavailable", None
    if response.status_code >= 400:
        return "download_failed", None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            payloads = []
            for name in archive.namelist():
                if name.endswith("/") or not name.endswith(".json"):
                    continue
                with archive.open(name) as handle:
                    payload = json.loads(handle.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    return "invalid_payload_format", None
                payloads.append(payload)
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return "invalid_payload_format", None
    return ("ok", payloads) if payloads else ("artifact_missing", None)


def inspect_run_artifact_payloads(bot, workflow_runs: list[dict], source_event_key: str, *, pr_number: int, source_event_kind: str) -> dict:
    payloads_by_run: dict[int, list[dict]] = {}
    prior_visibility: dict[int, dict[str, str]] = {}
    artifact_scan_outcomes: dict[int, str] = {}
    event_name, event_action = source_event_kind.split(":", 1)
    for run in workflow_runs:
        run_id = run.get("id")
        run_attempt = run.get("run_attempt")
        if not isinstance(run_id, int) or not isinstance(run_attempt, int):
            continue
        expected_name = artifact_expected_name({"source_event_name": event_name, "source_event_action": event_action, "source_run_id": run_id, "source_run_attempt": run_attempt})
        artifacts = _list_run_artifacts(bot, run_id)
        if artifacts is None:
            return {"status": "observer_state_unknown", "reason": "artifact_listing_unavailable", "payloads_by_run": None}
        filtered = []
        for artifact in artifacts:
            name = artifact.get("name")
            if not isinstance(name, str) or name != expected_name:
                continue
            filtered.append(artifact)
            prior_visibility[run_id] = {"artifact_seen_at": _now_iso(bot)}
            status, payloads = _download_artifact_payloads(bot, artifact)
            if status == "ok" and isinstance(payloads, list):
                matches = [
                    payload for payload in payloads
                    if _matching_payload(payload, run_id=run_id, run_attempt=run_attempt, event_name=event_name, event_action=event_action, source_event_key=source_event_key, pr_number=pr_number)
                ]
                if len(matches) == 1:
                    payloads_by_run.setdefault(run_id, []).append(matches[0])
                    artifact_scan_outcomes[run_id] = "ok"
                else:
                    artifact_scan_outcomes[run_id] = "artifact_invalid"
                    payloads_by_run.setdefault(run_id, [])
            elif status == "expired":
                prior_visibility[run_id]["artifact_last_downloadable_at"] = prior_visibility[run_id]["artifact_seen_at"]
                artifact_scan_outcomes[run_id] = "expired"
            else:
                artifact_scan_outcomes[run_id] = "artifact_missing" if status == "artifact_missing" else "artifact_invalid"
        if run_id not in payloads_by_run and filtered:
            payloads_by_run.setdefault(run_id, [])
    result = deferred_gap_diagnosis.correlate_run_artifacts_exact(payloads_by_run, source_event_key, pr_number=pr_number)
    result["payloads_by_run"] = payloads_by_run
    result["prior_visibility"] = prior_visibility
    result["artifact_scan_outcomes"] = artifact_scan_outcomes
    result["expected_payload_name"] = artifact_expected_payload_name({"source_event_name": event_name, "source_event_action": event_action})
    return result


def update_observer_watermark(bot, review_data: dict, surface: str, event_time: str, event_id: str) -> None:
    watermarks = gap_bookkeeping._observer_discovery_watermarks(review_data)
    current = watermarks.get(surface) if isinstance(watermarks.get(surface), dict) else {}
    watermarks[surface] = {
        "last_scan_started_at": current.get("last_scan_started_at") or _now_iso(bot),
        "last_scan_completed_at": _now_iso(bot),
        "last_safe_event_time": event_time,
        "last_safe_event_id": event_id,
        "lookback_seconds": bot.DEFERRED_DISCOVERY_OVERLAP_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS") else 3600,
        "bootstrap_window_seconds": bot.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS") else 604800,
        "bootstrap_completed_at": current.get("bootstrap_completed_at") or _now_iso(bot),
    }


def complete_surface_scan(bot, review_data: dict, surface: str, discovered: list[dict], load_surface_watermark) -> None:
    if discovered:
        last_seen = discovered[-1]
        update_observer_watermark(bot, review_data, surface, last_seen["source_created_at"], last_seen["object_id"])
        return
    watermark = load_surface_watermark(review_data, surface)
    watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso(bot)
    watermark["last_scan_completed_at"] = _now_iso(bot)
    watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso(bot)
