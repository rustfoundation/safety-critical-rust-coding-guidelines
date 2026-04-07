"""Deferred-gap bookkeeping support shared by reconcile and sweeper."""

from __future__ import annotations

from copy import deepcopy


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    review_data.setdefault("deferred_gaps", {})
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    review_data["deferred_gaps"][source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> bool:
    deferred_gaps = review_data.get("deferred_gaps")
    if isinstance(deferred_gaps, dict) and source_event_key in deferred_gaps:
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
