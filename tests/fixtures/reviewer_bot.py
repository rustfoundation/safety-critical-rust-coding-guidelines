import io
import json
import zipfile

from scripts import reviewer_bot


def make_state(epoch: str | None = None):
    state = {
        "schema_version": reviewer_bot.STATE_SCHEMA_VERSION,
        "freshness_runtime_epoch": epoch or reviewer_bot.FRESHNESS_RUNTIME_EPOCH_V18,
        "status_projection_epoch": reviewer_bot.STATUS_PROJECTION_EPOCH,
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
