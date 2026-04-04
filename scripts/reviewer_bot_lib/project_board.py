"""Reviewer board preflight and read-only preview helpers."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from .config import (
    REVIEWER_BOARD_ENABLED_ENV,
    REVIEWER_BOARD_FIELD_ASSIGNED_AT,
    REVIEWER_BOARD_FIELD_NEEDS_ATTENTION,
    REVIEWER_BOARD_FIELD_REVIEW_STATE,
    REVIEWER_BOARD_FIELD_REVIEWER,
    REVIEWER_BOARD_FIELD_WAITING_SINCE,
    REVIEWER_BOARD_OPTION_ATTENTION_NO,
    REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED,
    REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT,
    REVIEWER_BOARD_OPTION_ATTENTION_TRIAGE_APPROVAL_REQUIRED,
    REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT,
    REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR,
    REVIEWER_BOARD_OPTION_AWAITING_REVIEWER,
    REVIEWER_BOARD_OPTION_AWAITING_WRITE_APPROVAL,
    REVIEWER_BOARD_OPTION_DONE,
    REVIEWER_BOARD_OPTION_UNASSIGNED,
    REVIEWER_BOARD_ORG,
    REVIEWER_BOARD_PROJECT_MANIFEST,
    REVIEWER_BOARD_PROJECT_NUMBER,
)

PROJECT_BOARD_METADATA_QUERY = """
query ReviewerBoardProjectMetadata($organization: String!, $projectNumber: Int!) {
  organization(login: $organization) {
    projectV2(number: $projectNumber) {
      id
      title
      fields(first: 100) {
        nodes {
          __typename
          ... on ProjectV2FieldCommon {
            id
            name
          }
          ... on ProjectV2Field {
            dataType
          }
          ... on ProjectV2SingleSelectField {
            options {
              id
              name
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class ProjectFieldMetadata:
    field_id: str
    name: str
    field_type: str
    option_ids: dict[str, str]


@dataclass(frozen=True)
class ProjectMetadata:
    project_id: str
    project_title: str | None
    fields_by_name: dict[str, ProjectFieldMetadata]


@dataclass(frozen=True)
class ProjectBoardPreflight:
    enabled: bool
    configured: bool
    valid: bool
    project_id: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ReviewStateDerivation:
    state: str
    anchor_timestamp: str | None
    reason: str | None


@dataclass(frozen=True)
class BoardProjectionInput:
    issue_number: int
    classification: str
    review_state_derivation: ReviewStateDerivation | None
    review_data_snapshot: dict[str, Any] | None
    repair_targets: frozenset[str]
    live_item_closed: bool


@dataclass(frozen=True)
class BoardProjectionValues:
    review_state: str | None
    reviewer: str | None
    assigned_at: str | None
    waiting_since: str | None
    needs_attention: str | None
    archive: bool = False
    ensure_membership: bool = False


@dataclass(frozen=True)
class BoardPreviewResult:
    issue_number: int
    eligible: bool
    classification: str
    desired: BoardProjectionValues | None
    noop_reason: str | None


def reviewer_board_enabled(bot) -> bool:
    return bot.get_config_value(REVIEWER_BOARD_ENABLED_ENV, "false").strip().lower() == "true"


def _field_type_name(field_node: dict[str, Any]) -> str:
    typename = str(field_node.get("__typename", ""))
    if typename == "ProjectV2SingleSelectField":
        return "single_select"
    if typename == "ProjectV2Field":
        data_type = str(field_node.get("dataType", "")).upper()
        if data_type == "TEXT":
            return "text"
        if data_type == "DATE":
            return "date"
    return typename.lower()


def resolve_project_metadata(bot) -> ProjectMetadata:
    cached = getattr(bot, "_reviewer_board_project_metadata", None)
    if isinstance(cached, ProjectMetadata):
        return cached

    response = bot.github_graphql(
        PROJECT_BOARD_METADATA_QUERY,
        {
            "organization": REVIEWER_BOARD_ORG,
            "projectNumber": REVIEWER_BOARD_PROJECT_NUMBER,
        },
        token=bot.get_github_graphql_token(prefer_board_token=True),
    )
    organization = (response or {}).get("data", {}).get("organization") if isinstance(response, dict) else None
    project = organization.get("projectV2") if isinstance(organization, dict) else None
    if not isinstance(project, dict):
        raise RuntimeError(
            f"Unable to resolve reviewer board project {REVIEWER_BOARD_ORG}/{REVIEWER_BOARD_PROJECT_NUMBER}"
        )

    fields_by_name: dict[str, ProjectFieldMetadata] = {}
    nodes = ((project.get("fields") or {}).get("nodes") or []) if isinstance(project.get("fields"), dict) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        field_id = node.get("id")
        name = node.get("name")
        if not isinstance(field_id, str) or not isinstance(name, str):
            continue
        options = node.get("options") if isinstance(node.get("options"), list) else []
        option_ids = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            option_name = option.get("name")
            option_id = option.get("id")
            if isinstance(option_name, str) and isinstance(option_id, str):
                option_ids[option_name] = option_id
        fields_by_name[name] = ProjectFieldMetadata(
            field_id=field_id,
            name=name,
            field_type=_field_type_name(node),
            option_ids=option_ids,
        )

    metadata = ProjectMetadata(
        project_id=str(project.get("id", "")),
        project_title=project.get("title") if isinstance(project.get("title"), str) else None,
        fields_by_name=fields_by_name,
    )
    setattr(bot, "_reviewer_board_project_metadata", metadata)
    return metadata


def validate_project_manifest(bot, metadata: ProjectMetadata) -> tuple[str, ...]:
    del bot
    errors: list[str] = []
    for field_name, expected in REVIEWER_BOARD_PROJECT_MANIFEST.items():
        field = metadata.fields_by_name.get(field_name)
        if field is None:
            errors.append(f"Missing reviewer board field: {field_name}")
            continue
        if field.field_type != expected["type"]:
            errors.append(
                f"Field {field_name} has type {field.field_type}; expected {expected['type']}"
            )
        for option_name in expected.get("options", ()):
            if option_name not in field.option_ids:
                errors.append(f"Field {field_name} is missing option: {option_name}")
    return tuple(errors)


def reviewer_board_preflight(bot) -> ProjectBoardPreflight:
    if not reviewer_board_enabled(bot):
        return ProjectBoardPreflight(
            enabled=False,
            configured=True,
            valid=True,
            project_id=None,
            errors=(),
        )

    errors: list[str] = []
    project_id: str | None = None
    try:
        bot.get_github_graphql_token(prefer_board_token=True)
    except RuntimeError as exc:
        errors.append(str(exc))

    metadata = None
    if not errors:
        metadata = resolve_project_metadata(bot)
        project_id = metadata.project_id or None
        errors.extend(validate_project_manifest(bot, metadata))

    return ProjectBoardPreflight(
        enabled=True,
        configured=not errors,
        valid=not errors,
        project_id=project_id,
        errors=tuple(errors),
    )


def _classify_item(issue_snapshot: dict[str, Any] | None, review_data: dict[str, Any] | None) -> str:
    if isinstance(issue_snapshot, dict) and str(issue_snapshot.get("state", "")).lower() == "closed":
        return "closed"
    if not isinstance(review_data, dict):
        return "open_untracked"
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return "open_tracked_unassigned"
    return "open_tracked_assigned"


def _format_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:10]


def _derive_review_state(bot, issue_number: int, review_data_snapshot: dict[str, Any], issue_snapshot: dict[str, Any]) -> ReviewStateDerivation:
    preview_review_data = copy.deepcopy(review_data_snapshot)
    derived = bot.compute_reviewer_response_state(
        issue_number,
        preview_review_data,
        issue_snapshot=copy.deepcopy(issue_snapshot),
    )
    state = str(derived.get("state", "projection_failed"))
    return ReviewStateDerivation(
        state=state,
        anchor_timestamp=derived.get("anchor_timestamp") if isinstance(derived.get("anchor_timestamp"), str) else None,
        reason=derived.get("reason") if isinstance(derived.get("reason"), str) else None,
    )


def build_board_projection_input(bot, state: dict, issue_number: int, *, issue_snapshot: dict[str, Any] | None = None) -> BoardProjectionInput:
    if issue_snapshot is None:
        issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        raise RuntimeError(f"Unable to load issue or PR snapshot for #{issue_number}")

    active_reviews = state.get("active_reviews")
    review_data = active_reviews.get(str(issue_number)) if isinstance(active_reviews, dict) else None
    review_data_snapshot = copy.deepcopy(review_data) if isinstance(review_data, dict) else None
    classification = _classify_item(issue_snapshot, review_data_snapshot)
    review_state_derivation = None
    if classification == "open_tracked_assigned" and review_data_snapshot is not None:
        review_state_derivation = _derive_review_state(bot, issue_number, review_data_snapshot, issue_snapshot)

    return BoardProjectionInput(
        issue_number=issue_number,
        classification=classification,
        review_state_derivation=review_state_derivation,
        review_data_snapshot=review_data_snapshot,
        repair_targets=frozenset(),
        live_item_closed=classification == "closed",
    )


def derive_board_projection(input: BoardProjectionInput) -> BoardProjectionValues | None:
    if input.classification in {"closed", "open_untracked"}:
        return BoardProjectionValues(
            review_state=None,
            reviewer=None,
            assigned_at=None,
            waiting_since=None,
            needs_attention=None,
            archive=True,
            ensure_membership=False,
        )

    review_data = input.review_data_snapshot or {}
    if input.classification == "open_tracked_unassigned":
        return BoardProjectionValues(
            review_state=REVIEWER_BOARD_OPTION_UNASSIGNED,
            reviewer=None,
            assigned_at=None,
            waiting_since=None,
            needs_attention=REVIEWER_BOARD_OPTION_ATTENTION_NO,
            ensure_membership=True,
        )

    derivation = input.review_state_derivation
    if derivation is None:
        raise RuntimeError(f"Board derivation unavailable for #{input.issue_number}")
    if derivation.state == "projection_failed":
        raise RuntimeError(
            f"Board derivation failed for #{input.issue_number}: {derivation.reason or 'unknown reason'}"
        )

    review_state_map = {
        "awaiting_reviewer_response": REVIEWER_BOARD_OPTION_AWAITING_REVIEWER,
        "awaiting_contributor_response": REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR,
        "awaiting_write_approval": REVIEWER_BOARD_OPTION_AWAITING_WRITE_APPROVAL,
        "done": REVIEWER_BOARD_OPTION_DONE,
    }
    review_state = review_state_map.get(derivation.state)
    if review_state is None:
        raise RuntimeError(f"Unsupported board review state for #{input.issue_number}: {derivation.state}")

    needs_attention = REVIEWER_BOARD_OPTION_ATTENTION_NO
    repair_needed = review_data.get("repair_needed")
    if isinstance(repair_needed, dict) and repair_needed.get("kind") == "projection_failure":
        needs_attention = REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED
    elif review_data.get("mandatory_approver_required"):
        needs_attention = REVIEWER_BOARD_OPTION_ATTENTION_TRIAGE_APPROVAL_REQUIRED
    elif review_data.get("transition_notice_sent_at"):
        needs_attention = REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT
    elif review_data.get("transition_warning_sent"):
        needs_attention = REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT

    return BoardProjectionValues(
        review_state=review_state,
        reviewer=review_data.get("current_reviewer") if isinstance(review_data.get("current_reviewer"), str) and review_data.get("current_reviewer").strip() else None,
        assigned_at=_format_date(review_data.get("assigned_at")),
        waiting_since=_format_date(derivation.anchor_timestamp),
        needs_attention=needs_attention,
        ensure_membership=True,
    )


def preview_board_projection_for_item(bot, state: dict, issue_number: int) -> BoardPreviewResult:
    issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
    input = build_board_projection_input(bot, state, issue_number, issue_snapshot=issue_snapshot)
    desired = derive_board_projection(input)
    return BoardPreviewResult(
        issue_number=issue_number,
        eligible=input.classification in {"open_tracked_assigned", "open_tracked_unassigned"},
        classification=input.classification,
        desired=desired,
        noop_reason=None,
    )


def format_preview_for_output(preflight: ProjectBoardPreflight, previews: list[BoardPreviewResult]) -> list[dict[str, Any]]:
    rendered = [
        {
            "enabled": preflight.enabled,
            "configured": preflight.configured,
            "valid": preflight.valid,
            "project_id": preflight.project_id,
            "required_fields": [
                REVIEWER_BOARD_FIELD_REVIEW_STATE,
                REVIEWER_BOARD_FIELD_REVIEWER,
                REVIEWER_BOARD_FIELD_ASSIGNED_AT,
                REVIEWER_BOARD_FIELD_WAITING_SINCE,
                REVIEWER_BOARD_FIELD_NEEDS_ATTENTION,
            ],
        }
    ]
    for preview in previews:
        preview_dict = asdict(preview)
        desired = preview_dict.get("desired")
        if desired is None:
            rendered.append(preview_dict)
            continue
        preview_dict["desired"] = {
            key: value
            for key, value in desired.items()
            if value is not None or key in {"archive", "ensure_membership"}
        }
        rendered.append(preview_dict)
    return rendered
