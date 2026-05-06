"""Deferred-gap bookkeeping support shared by reconcile and sweeper."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class DeferredGap:
    source_event_key: str
    workflow_name: str | None
    workflow_file: str | None
    run_id: str | None
    run_attempt: str | None
    issue_number: int | None
    source_event_action: str | None
    failure_kind: str
    diagnostic_reason: str | None
    replay_allowed: bool
    recorded_at: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "source_event_key": self.source_event_key,
            "workflow_name": self.workflow_name,
            "workflow_file": self.workflow_file,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "issue_number": self.issue_number,
            "source_event_action": self.source_event_action,
            "failure_kind": self.failure_kind,
            "diagnostic_reason": self.diagnostic_reason,
            "replay_allowed": self.replay_allowed,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class ObserverWatermark:
    workflow_name: str
    workflow_file: str | None
    run_id: str | None
    run_attempt: str | None
    conclusion: str | None
    artifact_name: str | None
    artifact_path: str | None
    diagnostics_retained: bool
    recorded_at: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "workflow_name": self.workflow_name,
            "workflow_file": self.workflow_file,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "conclusion": self.conclusion,
            "artifact_name": self.artifact_name,
            "artifact_path": self.artifact_path,
            "diagnostics_retained": self.diagnostics_retained,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class ReconciledSourceEvent:
    source_event_key: str
    issue_number: int | None
    source_event_action: str | None
    replay_decision: str
    mark_reconciled: bool
    clear_gap: bool
    reconciled_at: str | None
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "source_event_key": self.source_event_key,
            "issue_number": self.issue_number,
            "source_event_action": self.source_event_action,
            "replay_decision": self.replay_decision,
            "mark_reconciled": self.mark_reconciled,
            "clear_gap": self.clear_gap,
            "reconciled_at": self.reconciled_at,
            "diagnostic_reason": self.diagnostic_reason,
        }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def from_deferred_gap_state(row: dict[str, object]) -> DeferredGap:
    return DeferredGap(
        source_event_key=str(row.get("source_event_key") or ""),
        workflow_name=_optional_str(row.get("workflow_name") or row.get("source_workflow_name")),
        workflow_file=_optional_str(row.get("workflow_file") or row.get("source_workflow_file")),
        run_id=str(row.get("source_run_id")) if row.get("source_run_id") is not None else None,
        run_attempt=str(row.get("source_run_attempt")) if row.get("source_run_attempt") is not None else None,
        issue_number=_optional_int(row.get("pr_number") or row.get("issue_number")),
        source_event_action=_optional_str(row.get("source_event_kind") or row.get("source_event_action")),
        failure_kind=str(row.get("failure_kind") or row.get("reason") or "unknown"),
        diagnostic_reason=_optional_str(row.get("diagnostic_summary") or row.get("diagnostic_reason")),
        replay_allowed=False,
        recorded_at=_optional_str(row.get("last_checked_at") or row.get("first_noted_at")),
    )


def validate_deferred_gap(gap: DeferredGap) -> DeferredGap:
    if not gap.source_event_key:
        raise RuntimeError("DeferredGap.source_event_key must be non-empty")
    return gap


def from_observer_watermark_state(row: dict[str, object]) -> ObserverWatermark:
    return ObserverWatermark(
        workflow_name=str(row.get("workflow_name") or row.get("surface") or ""),
        workflow_file=_optional_str(row.get("workflow_file")),
        run_id=str(row.get("run_id")) if row.get("run_id") is not None else None,
        run_attempt=str(row.get("run_attempt")) if row.get("run_attempt") is not None else None,
        conclusion=_optional_str(row.get("conclusion")),
        artifact_name=_optional_str(row.get("artifact_name")),
        artifact_path=_optional_str(row.get("artifact_path")),
        diagnostics_retained=bool(row.get("diagnostics_retained", False)),
        recorded_at=_optional_str(row.get("last_scan_completed_at") or row.get("recorded_at")),
    )


def validate_observer_watermark(watermark: ObserverWatermark) -> ObserverWatermark:
    if not watermark.workflow_name:
        raise RuntimeError("ObserverWatermark.workflow_name must be non-empty")
    return watermark


def from_reconciled_source_event_state(row: dict[str, object]) -> ReconciledSourceEvent:
    return ReconciledSourceEvent(
        source_event_key=str(row.get("source_event_key") or ""),
        issue_number=_optional_int(row.get("issue_number")),
        source_event_action=_optional_str(row.get("source_event_action")),
        replay_decision=str(row.get("replay_decision") or "pass_replayed_and_persisted"),
        mark_reconciled=bool(row.get("mark_reconciled", True)),
        clear_gap=bool(row.get("clear_gap", True)),
        reconciled_at=_optional_str(row.get("reconciled_at")),
        diagnostic_reason=_optional_str(row.get("diagnostic_reason")),
    )


def validate_reconciled_source_event(event: ReconciledSourceEvent) -> ReconciledSourceEvent:
    if not event.source_event_key:
        raise RuntimeError("ReconciledSourceEvent.source_event_key must be non-empty")
    if event.mark_reconciled and not event.reconciled_at:
        raise RuntimeError("ReconciledSourceEvent.reconciled_at is required when marked reconciled")
    return event


def _sidecars(review_data: dict) -> dict:
    sidecars = review_data.get("sidecars")
    if not isinstance(sidecars, dict):
        sidecars = {}
        review_data["sidecars"] = sidecars
    return sidecars


def _deferred_gaps(review_data: dict) -> dict:
    sidecars = _sidecars(review_data)
    deferred_gaps = sidecars.get("deferred_gaps")
    if not isinstance(deferred_gaps, dict):
        deferred_gaps = {}
        sidecars["deferred_gaps"] = deferred_gaps
    return deferred_gaps


def _reconciled_source_events(review_data: dict) -> dict:
    sidecars = _sidecars(review_data)
    reconciled = sidecars.get("reconciled_source_events")
    if not isinstance(reconciled, dict):
        reconciled = {}
        sidecars["reconciled_source_events"] = reconciled
    return reconciled


def _observer_discovery_watermarks(review_data: dict) -> dict:
    sidecars = _sidecars(review_data)
    watermarks = sidecars.get("observer_discovery_watermarks")
    if not isinstance(watermarks, dict):
        watermarks = {}
        sidecars["observer_discovery_watermarks"] = watermarks
    return watermarks


def _ensure_observer_discovery_watermark(review_data: dict, surface: str) -> dict:
    watermarks = _observer_discovery_watermarks(review_data)
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


def _observer_now_iso(bot) -> str:
    return _now_iso(bot)


def _parse_observer_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _configured_seconds(bot, name: str, default: int) -> int:
    value = getattr(bot, name, default)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return default
    return seconds if seconds >= 0 else default


def begin_observer_surface_scan(
    bot,
    review_data: dict,
    surface: str,
    *,
    now: datetime | None = None,
) -> datetime:
    watermark = _ensure_observer_discovery_watermark(review_data, surface)
    scan_started_at = now or bot.clock.now()
    if scan_started_at.tzinfo is None:
        scan_started_at = scan_started_at.replace(tzinfo=timezone.utc)
    lookback_seconds = _configured_seconds(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS", 3600)
    bootstrap_window_seconds = _configured_seconds(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS", 604800)
    watermark.update(
        {
            "last_scan_started_at": scan_started_at.isoformat(),
            "lookback_seconds": lookback_seconds,
            "bootstrap_window_seconds": bootstrap_window_seconds,
        }
    )
    bootstrap_floor = scan_started_at - timedelta(seconds=bootstrap_window_seconds)
    safe_time = _parse_observer_timestamp(watermark.get("last_safe_event_time"))
    if safe_time is None:
        return bootstrap_floor
    return max(bootstrap_floor, safe_time - timedelta(seconds=lookback_seconds))


def record_observer_watermark_event(bot, review_data: dict, surface: str, event_time: str, event_id: str) -> None:
    current = _ensure_observer_discovery_watermark(review_data, surface)
    now = _observer_now_iso(bot)
    current.update(
        {
            "last_scan_started_at": current.get("last_scan_started_at") or now,
            "last_scan_completed_at": now,
            "last_safe_event_time": event_time,
            "last_safe_event_id": event_id,
            "lookback_seconds": _configured_seconds(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS", 3600),
            "bootstrap_window_seconds": _configured_seconds(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS", 604800),
            "bootstrap_completed_at": current.get("bootstrap_completed_at") or now,
        }
    )


def record_observer_watermark_empty_scan(bot, review_data: dict, surface: str) -> None:
    watermark = _ensure_observer_discovery_watermark(review_data, surface)
    now = _observer_now_iso(bot)
    watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or now
    watermark["last_scan_completed_at"] = now
    watermark["lookback_seconds"] = _configured_seconds(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS", 3600)
    watermark["bootstrap_window_seconds"] = _configured_seconds(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS", 604800)
    watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or now


def list_deferred_gap_keys(review_data: dict) -> list[str]:
    return list(_deferred_gaps(review_data))


def get_deferred_gap(review_data: dict, source_event_key: str) -> dict:
    gap = _deferred_gaps(review_data).get(source_event_key)
    return gap if isinstance(gap, dict) else {}


def get_deferred_gap_reason(review_data: dict, source_event_key: str) -> str | None:
    reason = get_deferred_gap(review_data, source_event_key).get("reason")
    return reason if isinstance(reason, str) else None


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def _reconciled_at_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_reconciled_source_event(existing: object, source_event_key: str) -> bool:
    if not isinstance(existing, dict):
        return False
    if existing.get("source_event_key") != source_event_key:
        return False
    reconciled_at = existing.get("reconciled_at")
    return isinstance(reconciled_at, str) and bool(reconciled_at.strip())


def record_deferred_gap_payload(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    deferred_gaps = _deferred_gaps(review_data)
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    deferred_gaps[source_event_key] = payload


def clear_deferred_gap(review_data: dict, source_event_key: str) -> bool:
    deferred_gaps = _deferred_gaps(review_data)
    if source_event_key in deferred_gaps:
        deferred_gaps.pop(source_event_key, None)
        return True
    return False


def clear_automation_comment_false_positive(review_data: dict, source_event_key: str) -> bool:
    """Clear only known self-authored issue-comment observer false positives."""
    if not source_event_key.startswith("issue_comment:"):
        return False
    return clear_deferred_gap(review_data, source_event_key)


def update_deferred_gap_fields(review_data: dict, source_event_key: str, fields: dict) -> bool:
    deferred_gaps = _deferred_gaps(review_data)
    existing = deferred_gaps.get(source_event_key)
    if not isinstance(existing, dict):
        return False
    previous = deepcopy(existing)
    existing.update(fields)
    return previous != existing


def mark_reconciled_source_event(
    review_data: dict,
    source_event_key: str,
    *,
    reconciled_at: str | None = None,
) -> bool:
    reconciled = _reconciled_source_events(review_data)
    timestamp = reconciled_at or _reconciled_at_now()
    existing = reconciled.get(source_event_key)
    if isinstance(existing, dict):
        if not _is_valid_reconciled_source_event(existing, source_event_key):
            existing["source_event_key"] = source_event_key
            existing["reconciled_at"] = timestamp
            return True
        return False
    reconciled[source_event_key] = {
        "source_event_key": source_event_key,
        "reconciled_at": timestamp,
    }
    return True


def was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    return _is_valid_reconciled_source_event(
        _reconciled_source_events(review_data).get(source_event_key),
        source_event_key,
    )


def _payload_or_existing(payload: dict, existing: dict, key: str):
    value = payload.get(key)
    return existing.get(key) if value is None else value


def _first_present_payload_value(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value is not None and value != "":
            return value
    return None


def _copy_source_evidence(fields: dict, payload: dict, existing: dict) -> None:
    evidence_fields = {
        "source_actor_login": ("source_actor_login", "comment_author", "actor_login"),
        "source_actor_id": ("source_actor_id", "comment_author_id", "actor_id"),
        "source_actor_user_type": ("source_actor_user_type", "comment_user_type"),
        "source_actor_sender_type": ("source_actor_sender_type", "comment_sender_type"),
        "source_actor_installation_id": ("source_actor_installation_id", "comment_installation_id"),
        "source_actor_performed_via_github_app": (
            "source_actor_performed_via_github_app",
            "comment_performed_via_github_app",
        ),
        "source_comment_id": ("source_comment_id", "comment_id"),
        "source_review_id": ("source_review_id", "review_id", "pull_request_review_id"),
        "source_commit_id": ("source_commit_id",),
        "source_review_state": ("source_review_state",),
    }
    for target_key, source_keys in evidence_fields.items():
        value = _first_present_payload_value(payload, source_keys)
        if value is None:
            value = existing.get(target_key)
        if value is not None:
            fields[target_key] = value


def _source_event_created_at(payload: dict, existing: dict):
    return (
        payload.get("source_created_at")
        or payload.get("comment_created_at")
        or payload.get("source_submitted_at")
        or payload.get("source_dismissed_at")
        or payload.get("source_event_created_at")
        or existing.get("source_event_created_at")
    )


def record_deferred_gap_diagnostic(
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
    deferred_gaps = _deferred_gaps(review_data)
    existing = deferred_gaps.get(source_event_key, {})
    if not isinstance(existing, dict):
        existing = {}
    previous = deepcopy(existing)
    fields = {
        "source_event_key": source_event_key,
        "source_event_kind": f"{payload.get('source_event_name')}:{payload.get('source_event_action')}",
        "pr_number": payload.get("pr_number"),
        "reason": reason,
        "source_event_created_at": _source_event_created_at(payload, existing),
        "source_run_id": _payload_or_existing(payload, existing, "source_run_id"),
        "source_run_attempt": _payload_or_existing(payload, existing, "source_run_attempt"),
        "source_workflow_file": _payload_or_existing(payload, existing, "source_workflow_file"),
        "source_artifact_name": _payload_or_existing(payload, existing, "source_artifact_name"),
        "first_noted_at": existing.get("first_noted_at") or _now_iso(bot),
        "last_checked_at": _now_iso(bot),
        "operator_action_required": True,
        "diagnostic_summary": diagnostic_summary,
        "failure_kind": failure_kind,
    }
    source_dismissed_at = _payload_or_existing(payload, existing, "source_dismissed_at")
    if source_dismissed_at is not None:
        fields["source_dismissed_at"] = source_dismissed_at
    _copy_source_evidence(fields, payload, existing)
    existing.update(fields)
    changed = previous != existing
    deferred_gaps[source_event_key] = existing
    return changed
