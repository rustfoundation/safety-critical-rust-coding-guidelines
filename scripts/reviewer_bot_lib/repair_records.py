"""Repair-marker sidecar storage helpers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class RepairMarker:
    issue_number: int
    repair_kind: str
    target_collection_mode: str
    source_event_key: str | None
    artifact_name: str | None
    repaired_at: str | None
    result: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "repair_kind": self.repair_kind,
            "target_collection_mode": self.target_collection_mode,
            "source_event_key": self.source_event_key,
            "artifact_name": self.artifact_name,
            "repaired_at": self.repaired_at,
            "result": self.result,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class ProjectionRepairMarker:
    issue_number: int
    repair_action: str
    target_collection_mode: str
    status_projection_epoch: str | None
    before_status_labels: tuple[str, ...]
    desired_status_labels: tuple[str, ...]
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    repaired_at: str | None
    result: str

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "repair_action": self.repair_action,
            "target_collection_mode": self.target_collection_mode,
            "status_projection_epoch": self.status_projection_epoch,
            "before_status_labels": sorted(self.before_status_labels),
            "desired_status_labels": sorted(self.desired_status_labels),
            "labels_added": sorted(self.labels_added),
            "labels_removed": sorted(self.labels_removed),
            "repaired_at": self.repaired_at,
            "result": self.result,
        }


def from_repair_marker_state(row: dict[str, object]) -> RepairMarker:
    return RepairMarker(
        issue_number=int(row.get("issue_number") or 0),
        repair_kind=str(row.get("kind") or row.get("repair_kind") or "unknown"),
        target_collection_mode=str(row.get("target_collection_mode") or "single_issue"),
        source_event_key=row.get("source_event_key") if isinstance(row.get("source_event_key"), str) else None,
        artifact_name=row.get("artifact_name") if isinstance(row.get("artifact_name"), str) else None,
        repaired_at=row.get("repaired_at") or row.get("recorded_at") if isinstance(row.get("repaired_at") or row.get("recorded_at"), str) else None,
        result=str(row.get("result") or "blocked"),
        diagnostic_reason=row.get("reason") if isinstance(row.get("reason"), str) else None,
    )


def validate_repair_marker(marker: RepairMarker) -> RepairMarker:
    if marker.issue_number < 0:
        raise RuntimeError("RepairMarker.issue_number must be non-negative")
    return marker


def from_projection_repair_marker_state(row: dict[str, object]) -> ProjectionRepairMarker:
    return ProjectionRepairMarker(
        issue_number=int(row.get("issue_number") or 0),
        repair_action=str(row.get("repair_action") or row.get("kind") or "projection_failure"),
        target_collection_mode=str(row.get("target_collection_mode") or "single_issue"),
        status_projection_epoch=row.get("status_projection_epoch") if isinstance(row.get("status_projection_epoch"), str) else None,
        before_status_labels=tuple(str(value) for value in row.get("before_status_labels", ()) if isinstance(value, str)),
        desired_status_labels=tuple(str(value) for value in row.get("desired_status_labels", ()) if isinstance(value, str)),
        labels_added=tuple(str(value) for value in row.get("labels_added", ()) if isinstance(value, str)),
        labels_removed=tuple(str(value) for value in row.get("labels_removed", ()) if isinstance(value, str)),
        repaired_at=row.get("repaired_at") if isinstance(row.get("repaired_at"), str) else None,
        result=str(row.get("result") or "blocked"),
    )


def validate_projection_repair_marker(marker: ProjectionRepairMarker) -> ProjectionRepairMarker:
    if marker.issue_number < 0:
        raise RuntimeError("ProjectionRepairMarker.issue_number must be non-negative")
    return marker

_REPAIR_MARKER_KEYS = (
    "review_repair",
    "head_observation_repair",
    "status_label_projection",
    "issue_snapshot_read",
    "warning_dedupe_read",
    "warning_post",
    "transition_dedupe_read",
    "transition_post",
    "assignment_add_write",
    "assignment_remove_write",
    "assignment_confirm_read",
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
    if not isinstance(markers.get(key), dict):
        return False
    markers[key] = None
    return True
