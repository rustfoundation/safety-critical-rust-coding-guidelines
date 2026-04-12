"""Repair-marker sidecar storage helpers."""

from __future__ import annotations

from copy import deepcopy

_REPAIR_MARKER_KEYS = (
    "review_repair",
    "head_observation_repair",
    "status_label_projection",
)


def _sidecars(review_data: dict) -> dict:
    sidecars = review_data.get("sidecars")
    if not isinstance(sidecars, dict):
        sidecars = {}
        review_data["sidecars"] = sidecars
    return sidecars


def repair_markers(review_data: dict) -> dict:
    markers = _sidecars(review_data).get("repair_markers")
    canonical = dict.fromkeys(_REPAIR_MARKER_KEYS)
    if isinstance(markers, dict):
        for key in _REPAIR_MARKER_KEYS:
            if isinstance(markers.get(key), dict):
                canonical[key] = deepcopy(markers[key])
    _sidecars(review_data)["repair_markers"] = canonical
    markers = canonical
    return markers


def projection_repair_marker(reason: str, recorded_at: str) -> dict:
    return {
        "kind": "projection_failure",
        "reason": reason,
        "recorded_at": recorded_at,
    }


def maintenance_repair_marker(*, reason: str, failure_kind: str | None, recorded_at: str) -> dict:
    return {
        "kind": "live_read_failure",
        "reason": reason,
        "failure_kind": failure_kind,
        "recorded_at": recorded_at,
    }


def store_repair_marker(review_data: dict, key: str, marker: dict) -> bool:
    markers = repair_markers(review_data)
    existing = markers.get(key)
    if not isinstance(marker, dict):
        return False
    if isinstance(existing, dict) and {
        name: value for name, value in existing.items() if name != "recorded_at"
    } == {
        name: value for name, value in marker.items() if name != "recorded_at"
    }:
        return False
    markers[key] = deepcopy(marker)
    return True


def load_repair_marker(review_data: dict, key: str) -> dict | None:
    marker = repair_markers(review_data).get(key)
    return marker if isinstance(marker, dict) else None


def clear_repair_marker(review_data: dict, key: str) -> bool:
    markers = repair_markers(review_data)
    if key not in markers:
        return False
    markers[key] = None
    return True
