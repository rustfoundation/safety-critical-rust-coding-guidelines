import io
import json
import zipfile

from scripts.reviewer_bot_lib.config import (
    FRESHNESS_RUNTIME_EPOCH_V18,
    STATE_SCHEMA_VERSION,
    STATUS_PROJECTION_EPOCH,
)

from .reviewer_bot_builders import (
    accept_contributor_comment as accept_contributor_comment,
)
from .reviewer_bot_builders import (
    accept_contributor_revision as accept_contributor_revision,
)
from .reviewer_bot_builders import (
    accept_reviewer_comment as accept_reviewer_comment,
)
from .reviewer_bot_builders import (
    accept_reviewer_review as accept_reviewer_review,
)
from .reviewer_bot_builders import (
    accepted_record as accepted_record,
)
from .reviewer_bot_builders import (
    issue_snapshot as issue_snapshot,
)
from .reviewer_bot_builders import (
    make_tracked_review_state as make_tracked_review_state,
)
from .reviewer_bot_builders import (
    pull_request_payload as pull_request_payload,
)
from .reviewer_bot_builders import (
    review_payload as review_payload,
)

__all__ = [
    "accept_contributor_comment",
    "accept_contributor_revision",
    "accept_reviewer_comment",
    "accept_reviewer_review",
    "accepted_record",
    "issue_snapshot",
    "iso_z",
    "make_state",
    "make_tracked_review_state",
    "make_zip_payload",
    "pull_request_payload",
    "review_payload",
    "valid_reviewer_board_metadata",
]


def make_state(epoch: str | None = None):
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "freshness_runtime_epoch": epoch or FRESHNESS_RUNTIME_EPOCH_V18,
        "status_projection_epoch": STATUS_PROJECTION_EPOCH,
        "last_updated": None,
        "current_index": 0,
        "queue": [
            {"github": "alice", "name": "Alice"},
            {"github": "bob", "name": "Bob"},
            {"github": "carol", "name": "Carol"},
        ],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }
    if epoch == "freshness_v15":
        state["freshness_runtime_epoch"] = epoch
        state.pop("status_projection_epoch", None)
    return state


def valid_reviewer_board_metadata():
    return {
        "data": {
            "organization": {
                "projectV2": {
                    "id": "PVT_kwDOB",
                    "title": "Reviewer Board",
                    "fields": {
                        "nodes": [
                            {
                                "__typename": "ProjectV2SingleSelectField",
                                "id": "field-review-state",
                                "name": "Review State",
                                "options": [
                                    {"id": "opt-ar", "name": "Awaiting Reviewer"},
                                    {"id": "opt-ac", "name": "Awaiting Contributor"},
                                    {"id": "opt-aw", "name": "Awaiting Write Approval"},
                                    {"id": "opt-done", "name": "Done"},
                                    {"id": "opt-unassigned", "name": "Unassigned"},
                                ],
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "TEXT",
                                "id": "field-reviewer",
                                "name": "Reviewer",
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "DATE",
                                "id": "field-assigned-at",
                                "name": "Assigned At",
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "DATE",
                                "id": "field-waiting-since",
                                "name": "Waiting Since",
                            },
                            {
                                "__typename": "ProjectV2SingleSelectField",
                                "id": "field-needs-attention",
                                "name": "Needs Attention",
                                "options": [
                                    {"id": "opt-no", "name": "No"},
                                    {"id": "opt-warning", "name": "Warning Sent"},
                                    {"id": "opt-notice", "name": "Transition Notice Sent"},
                                    {"id": "opt-triage", "name": "Triage Approval Required"},
                                    {"id": "opt-repair", "name": "Projection Repair Required"},
                                ],
                            },
                        ]
                    },
                }
            }
        }
    }


def iso_z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def make_zip_payload(file_name: str, payload: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(file_name, json.dumps(payload))
    return buffer.getvalue()
