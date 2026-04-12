"""Deferred-gap bookkeeping support shared by reconcile and sweeper."""

from __future__ import annotations

from copy import deepcopy


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


def get_deferred_gaps(review_data: dict) -> dict:
    return _deferred_gaps(review_data)


def _reconciled_source_events(review_data: dict) -> dict:
    sidecars = _sidecars(review_data)
    reconciled = sidecars.get("reconciled_source_events")
    if not isinstance(reconciled, dict):
        reconciled = {}
        sidecars["reconciled_source_events"] = reconciled
    return reconciled


def get_reconciled_source_events(review_data: dict) -> dict:
    return _reconciled_source_events(review_data)


def _observer_discovery_watermarks(review_data: dict) -> dict:
    sidecars = _sidecars(review_data)
    watermarks = sidecars.get("observer_discovery_watermarks")
    if not isinstance(watermarks, dict):
        watermarks = {}
        sidecars["observer_discovery_watermarks"] = watermarks
    return watermarks


def get_observer_discovery_watermarks(review_data: dict) -> dict:
    return _observer_discovery_watermarks(review_data)


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    deferred_gaps = _deferred_gaps(review_data)
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    deferred_gaps[source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> bool:
    deferred_gaps = _deferred_gaps(review_data)
    if source_event_key in deferred_gaps:
        deferred_gaps.pop(source_event_key, None)
        return True
    return False


def _mark_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = _reconciled_source_events(review_data)
    if source_event_key not in reconciled:
        reconciled[source_event_key] = {
            "source_event_key": source_event_key,
            "reconciled_at": None,
        }
        return True
    return False


def _was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    return source_event_key in _reconciled_source_events(review_data)


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
    deferred_gaps = _deferred_gaps(review_data)
    existing = deferred_gaps.get(source_event_key, {})
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
            "first_noted_at": existing.get("first_noted_at") or _now_iso(bot),
            "last_checked_at": _now_iso(bot),
            "operator_action_required": True,
            "diagnostic_summary": diagnostic_summary,
            "failure_kind": failure_kind,
        }
    )
    changed = previous != existing
    deferred_gaps[source_event_key] = existing
    return changed
