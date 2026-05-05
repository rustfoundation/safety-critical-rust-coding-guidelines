"""Deferred reconcile payload and identity helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DeferredPayloadKind(StrEnum):
    DEFERRED_COMMENT = "deferred_comment"
    DEFERRED_REVIEW_COMMENT = "deferred_review_comment"
    DEFERRED_REVIEW_SUBMITTED = "deferred_review_submitted"
    DEFERRED_REVIEW_DISMISSED = "deferred_review_dismissed"


@dataclass(frozen=True)
class DeferredArtifactIdentity:
    payload_kind: DeferredPayloadKind
    schema_version: int
    source_run_id: int
    source_run_attempt: int
    source_event_name: str
    source_event_action: str
    source_event_key: str
    pr_number: int


@dataclass(frozen=True)
class DeferredIdentityContract:
    payload_kind: DeferredPayloadKind
    source_event_name: str
    source_event_action: str
    source_event_key_prefix: str
    object_id_field: str
    actor_fields: tuple[str, ...]
    timestamp_fields: tuple[str, ...]


@dataclass(frozen=True)
class DeferredWorkflowSourceContract:
    payload_kind: str
    workflow_name: str
    workflow_file: str
    artifact_name_prefix: str
    source_event_name: str
    source_event_action: str
    source_event_key_prefix: str
    object_id_field: str
    required_payload_fields: tuple[str, ...]
    required_identity_fields: tuple[str, ...]
    live_endpoint_kind: str


@dataclass(frozen=True)
class DeferredArtifactSourceAuthority:
    workflow_name: str | None
    workflow_file: str | None
    run_id: str | None
    run_attempt: str | None
    artifact_name: str | None
    artifact_path: str | None
    source_event_key: str | None
    source_event_name: str | None
    source_event_action: str | None
    source_issue_number: int | None
    source_pr_number: int | None
    source_head_sha: str | None
    source_actor: str | None
    authority_status: str
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "workflow_name": self.workflow_name,
            "workflow_file": self.workflow_file,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_name": self.artifact_name,
            "artifact_path": self.artifact_path,
            "source_event_key": self.source_event_key,
            "source_event_name": self.source_event_name,
            "source_event_action": self.source_event_action,
            "source_issue_number": self.source_issue_number,
            "source_pr_number": self.source_pr_number,
            "source_head_sha": self.source_head_sha,
            "source_actor": self.source_actor,
            "authority_status": self.authority_status,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class RecoveredDeferredPayloadIdentity:
    source_run_id: int
    source_run_attempt: int
    source_event_name: str
    source_event_action: str
    source_event_key: str
    pr_number: int
    source_object_id: int
    actor_login: str
    source_event_created_at: str
    diagnostic_payload: dict


@dataclass(frozen=True)
class DeferredReviewPayload:
    identity: DeferredArtifactIdentity
    review_id: int
    source_submitted_at: str | None
    source_review_state: str | None
    source_commit_id: str | None
    actor_login: str | None
    raw_payload: dict

    @property
    def pr_number(self) -> int:
        return self.identity.pr_number


@dataclass(frozen=True)
class DeferredReviewSubmittedPayload(DeferredReviewPayload):
    pass


@dataclass(frozen=True)
class DeferredReviewDismissedPayload(DeferredReviewPayload):
    pass


@dataclass(frozen=True)
class DeferredCommentPayload:
    identity: DeferredArtifactIdentity
    comment_id: int
    comment_body: str
    comment_created_at: str
    comment_author: str
    comment_author_id: int
    comment_user_type: str
    comment_sender_type: str
    comment_installation_id: str | None
    comment_performed_via_github_app: bool
    issue_author: str
    issue_state: str
    issue_labels: tuple[str, ...]
    raw_payload: dict
    source_commit_id: str | None = None
    source_body_digest: str | None = None
    source_comment_class: str | None = None
    source_has_non_command_text: bool | None = None
    source_freshness_eligible: bool = True

    @property
    def pr_number(self) -> int:
        return self.identity.pr_number


@dataclass(frozen=True)
class DeferredCommentReplayContext:
    payload: DeferredCommentPayload
    expected_event_name: str
    live_comment_endpoint: str

    @property
    def source_event_key(self) -> str:
        return self.payload.identity.source_event_key

    @property
    def comment_id(self) -> int:
        return self.payload.comment_id

    @property
    def pr_number(self) -> int:
        return self.payload.identity.pr_number

    @property
    def actor_login(self) -> str:
        return self.payload.comment_author

    @property
    def source_created_at(self) -> str:
        return self.payload.comment_created_at

    @property
    def source_freshness_eligible(self) -> bool:
        return self.payload.source_freshness_eligible


@dataclass(frozen=True)
class DeferredReviewReplayContext:
    payload: DeferredReviewPayload

    @property
    def source_event_key(self) -> str:
        return self.payload.identity.source_event_key

    @property
    def review_id(self) -> int:
        return self.payload.review_id

    @property
    def pr_number(self) -> int:
        return self.payload.identity.pr_number

    @property
    def actor_login(self) -> str:
        return self.payload.actor_login or ""


_DEFERRED_IDENTITY_CONTRACTS: dict[DeferredPayloadKind, DeferredIdentityContract] = {
    DeferredPayloadKind.DEFERRED_COMMENT: DeferredIdentityContract(
        payload_kind=DeferredPayloadKind.DEFERRED_COMMENT,
        source_event_name="issue_comment",
        source_event_action="created",
        source_event_key_prefix="issue_comment:",
        object_id_field="comment_id",
        actor_fields=("source_actor_login", "comment_author", "actor_login"),
        timestamp_fields=("source_created_at", "comment_created_at", "source_event_created_at"),
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_COMMENT: DeferredIdentityContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_COMMENT,
        source_event_name="pull_request_review_comment",
        source_event_action="created",
        source_event_key_prefix="pull_request_review_comment:",
        object_id_field="comment_id",
        actor_fields=("source_actor_login", "comment_author", "actor_login"),
        timestamp_fields=("source_created_at", "comment_created_at", "source_event_created_at"),
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED: DeferredIdentityContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED,
        source_event_name="pull_request_review",
        source_event_action="submitted",
        source_event_key_prefix="pull_request_review:",
        object_id_field="review_id",
        actor_fields=("source_actor_login", "review_author", "actor_login"),
        timestamp_fields=("source_submitted_at", "source_event_created_at"),
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_DISMISSED: DeferredIdentityContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_DISMISSED,
        source_event_name="pull_request_review",
        source_event_action="dismissed",
        source_event_key_prefix="pull_request_review_dismissed:",
        object_id_field="review_id",
        actor_fields=("source_actor_login", "review_author", "actor_login"),
        timestamp_fields=("source_dismissed_at", "source_event_created_at"),
    ),
}
_DEFERRED_CONTRACTS_BY_EVENT: dict[tuple[str, str], DeferredIdentityContract] = {
    (contract.source_event_name, contract.source_event_action): contract
    for contract in _DEFERRED_IDENTITY_CONTRACTS.values()
}

_COMMON_REQUIRED_IDENTITY_FIELDS = (
    "workflow_name",
    "workflow_file",
    "run_id",
    "run_attempt",
    "artifact_name",
    "source_event_name",
    "source_event_action",
    "source_event_key",
    "source_pr_number",
)
_DEFERRED_WORKFLOW_SOURCE_CONTRACTS: dict[str, DeferredWorkflowSourceContract] = {
    DeferredPayloadKind.DEFERRED_COMMENT.value: DeferredWorkflowSourceContract(
        payload_kind=DeferredPayloadKind.DEFERRED_COMMENT.value,
        workflow_name="Reviewer Bot PR Comment Router",
        workflow_file=".github/workflows/reviewer-bot-pr-comment-router.yml",
        artifact_name_prefix="reviewer-bot-comment-context-",
        source_event_name="issue_comment",
        source_event_action="created",
        source_event_key_prefix="issue_comment:",
        object_id_field="comment_id",
        required_payload_fields=(
            "payload_kind",
            "schema_version",
            "source_run_id",
            "source_run_attempt",
            "source_event_name",
            "source_event_action",
            "source_event_key",
            "pr_number",
            "comment_id",
            "comment_body",
            "comment_created_at",
            "comment_author",
            "comment_author_id",
            "comment_user_type",
            "comment_sender_type",
            "comment_performed_via_github_app",
            "issue_author",
            "issue_state",
            "issue_labels",
        ),
        required_identity_fields=_COMMON_REQUIRED_IDENTITY_FIELDS,
        live_endpoint_kind="issue_comment",
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_COMMENT.value: DeferredWorkflowSourceContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_COMMENT.value,
        workflow_name="Reviewer Bot PR Review Comment Observer",
        workflow_file=".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
        artifact_name_prefix="reviewer-bot-review-comment-context-",
        source_event_name="pull_request_review_comment",
        source_event_action="created",
        source_event_key_prefix="pull_request_review_comment:",
        object_id_field="comment_id",
        required_payload_fields=(
            "payload_kind",
            "schema_version",
            "source_run_id",
            "source_run_attempt",
            "source_event_name",
            "source_event_action",
            "source_event_key",
            "pr_number",
            "comment_id",
            "comment_body",
            "comment_created_at",
            "comment_author",
            "comment_author_id",
            "comment_user_type",
            "comment_sender_type",
            "comment_performed_via_github_app",
            "issue_author",
            "issue_state",
            "issue_labels",
            "source_commit_id",
        ),
        required_identity_fields=_COMMON_REQUIRED_IDENTITY_FIELDS,
        live_endpoint_kind="review_comment",
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED.value: DeferredWorkflowSourceContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED.value,
        workflow_name="Reviewer Bot PR Review Submitted Observer",
        workflow_file=".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        artifact_name_prefix="reviewer-bot-review-submitted-context-",
        source_event_name="pull_request_review",
        source_event_action="submitted",
        source_event_key_prefix="pull_request_review:",
        object_id_field="review_id",
        required_payload_fields=(
            "payload_kind",
            "schema_version",
            "source_run_id",
            "source_run_attempt",
            "source_event_name",
            "source_event_action",
            "source_event_key",
            "pr_number",
            "review_id",
            "source_submitted_at",
            "source_review_state",
            "source_commit_id",
            "actor_login",
        ),
        required_identity_fields=_COMMON_REQUIRED_IDENTITY_FIELDS,
        live_endpoint_kind="pull_request_review",
    ),
    DeferredPayloadKind.DEFERRED_REVIEW_DISMISSED.value: DeferredWorkflowSourceContract(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_DISMISSED.value,
        workflow_name="Reviewer Bot PR Review Dismissed Observer",
        workflow_file=".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        artifact_name_prefix="reviewer-bot-review-dismissed-context-",
        source_event_name="pull_request_review",
        source_event_action="dismissed",
        source_event_key_prefix="pull_request_review_dismissed:",
        object_id_field="review_id",
        required_payload_fields=(
            "payload_kind",
            "schema_version",
            "source_run_id",
            "source_run_attempt",
            "source_event_name",
            "source_event_action",
            "source_event_key",
            "pr_number",
            "review_id",
        ),
        required_identity_fields=_COMMON_REQUIRED_IDENTITY_FIELDS,
        live_endpoint_kind="pull_request_review",
    ),
}


def deferred_workflow_source_contract_for_payload_kind(payload_kind: str) -> DeferredWorkflowSourceContract:
    try:
        return _DEFERRED_WORKFLOW_SOURCE_CONTRACTS[payload_kind]
    except KeyError as exc:
        raise RuntimeError("Unsupported deferred workflow source contract payload kind") from exc


def _raw_identity_value(identity: DeferredArtifactIdentity | None, raw_payload: dict, field_name: str) -> object:
    if identity is not None:
        if field_name == "run_id":
            return identity.source_run_id
        if field_name == "run_attempt":
            return identity.source_run_attempt
        if field_name == "source_event_name":
            return identity.source_event_name
        if field_name == "source_event_action":
            return identity.source_event_action
        if field_name == "source_event_key":
            return identity.source_event_key
        if field_name == "source_pr_number":
            return identity.pr_number
    aliases = {
        "workflow_name": ("workflow_name", "source_workflow_name"),
        "workflow_file": ("workflow_file", "source_workflow_file"),
        "run_id": ("run_id", "source_run_id"),
        "run_attempt": ("run_attempt", "source_run_attempt"),
        "artifact_name": ("artifact_name", "source_artifact_name"),
        "source_pr_number": ("source_pr_number", "pr_number"),
    }.get(field_name, (field_name,))
    for alias in aliases:
        if alias in raw_payload:
            return raw_payload.get(alias)
    return None


def derive_deferred_artifact_source_authority(
    identity: DeferredArtifactIdentity | None,
    raw_payload: dict,
    *,
    triggering_conclusion: str | None = None,
    contract: DeferredWorkflowSourceContract | None = None,
) -> DeferredArtifactSourceAuthority:
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    payload_kind = raw_payload.get("payload_kind")
    if contract is None:
        contract = deferred_workflow_source_contract_for_payload_kind(str(payload_kind))
    missing_payload = [field for field in contract.required_payload_fields if field not in raw_payload]
    missing_identity = [
        field
        for field in contract.required_identity_fields
        if _raw_identity_value(identity, raw_payload, field) in {None, ""}
    ]
    workflow_name = _raw_identity_value(identity, raw_payload, "workflow_name")
    workflow_file = _raw_identity_value(identity, raw_payload, "workflow_file")
    artifact_name = _raw_identity_value(identity, raw_payload, "artifact_name")
    source_event_key = _raw_identity_value(identity, raw_payload, "source_event_key")
    object_id = raw_payload.get(contract.object_id_field)
    expected_key = f"{contract.source_event_key_prefix}{object_id}"
    status = "trusted_exact_identity"
    reason = None
    if identity is not None and identity.schema_version == 2:
        status = "trusted_legacy_identity"
    elif identity is None or missing_identity:
        status = "blocked_missing_identity"
        reason = "missing_identity_fields:" + ",".join(missing_identity)
    elif missing_payload:
        status = "blocked_source_mismatch"
        reason = "missing_payload_fields:" + ",".join(missing_payload)
    elif triggering_conclusion and triggering_conclusion != "success":
        status = "diagnostic_non_success_identity"
        reason = f"triggering_conclusion:{triggering_conclusion}"
    elif workflow_name != contract.workflow_name or workflow_file != contract.workflow_file:
        status = "blocked_source_mismatch"
        reason = "workflow_identity_mismatch"
    elif not isinstance(artifact_name, str) or not artifact_name.startswith(contract.artifact_name_prefix):
        status = "blocked_source_mismatch"
        reason = "artifact_name_prefix_mismatch"
    elif raw_payload.get("source_event_name") != contract.source_event_name or raw_payload.get("source_event_action") != contract.source_event_action:
        status = "blocked_action_mismatch"
        reason = "source_event_action_mismatch"
    elif source_event_key != expected_key:
        status = "blocked_source_mismatch"
        reason = "source_event_key_object_mismatch"
    return DeferredArtifactSourceAuthority(
        workflow_name=str(workflow_name) if workflow_name is not None else None,
        workflow_file=str(workflow_file) if workflow_file is not None else None,
        run_id=str(_raw_identity_value(identity, raw_payload, "run_id")) if _raw_identity_value(identity, raw_payload, "run_id") is not None else None,
        run_attempt=str(_raw_identity_value(identity, raw_payload, "run_attempt")) if _raw_identity_value(identity, raw_payload, "run_attempt") is not None else None,
        artifact_name=str(artifact_name) if artifact_name is not None else None,
        artifact_path=str(raw_payload.get("artifact_path")) if raw_payload.get("artifact_path") is not None else None,
        source_event_key=str(source_event_key) if source_event_key is not None else None,
        source_event_name=str(raw_payload.get("source_event_name")) if raw_payload.get("source_event_name") is not None else None,
        source_event_action=str(raw_payload.get("source_event_action")) if raw_payload.get("source_event_action") is not None else None,
        source_issue_number=int(raw_payload["issue_number"]) if isinstance(raw_payload.get("issue_number"), int) else None,
        source_pr_number=int(raw_payload["pr_number"]) if isinstance(raw_payload.get("pr_number"), int) else None,
        source_head_sha=str(raw_payload.get("source_commit_id")) if raw_payload.get("source_commit_id") is not None else None,
        source_actor=str(raw_payload.get("comment_author") or raw_payload.get("actor_login") or raw_payload.get("source_actor_login") or "") or None,
        authority_status=status,
        diagnostic_reason=reason,
    )


def _contract_for_event(source_event_name: object, source_event_action: object) -> DeferredIdentityContract | None:
    if not isinstance(source_event_name, str) or not isinstance(source_event_action, str):
        return None
    return _DEFERRED_CONTRACTS_BY_EVENT.get((source_event_name.strip(), source_event_action.strip()))


def _positive_int(payload: dict, field_name: str) -> int:
    try:
        value = int(payload.get(field_name))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Deferred context payload lacks a recoverable {field_name}") from exc
    if value <= 0:
        raise RuntimeError(f"Deferred context payload lacks a recoverable {field_name}")
    return value


def _nonempty_string(payload: dict, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Deferred context payload lacks a recoverable {field_name}")
    return value.strip()


def _first_string(payload: dict, field_names: tuple[str, ...], diagnostic_name: str) -> str:
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError(f"Deferred context payload lacks a recoverable {diagnostic_name}")


def _recoverable_timestamp(payload: dict, field_names: tuple[str, ...]) -> str:
    timestamp = _first_string(payload, field_names, "source event timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("Deferred context payload source event timestamp is not parseable ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("Deferred context payload source event timestamp must include timezone")
    return timestamp


def _optional_nonempty_string(payload: dict, field_name: str) -> str | None:
    value = payload.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _diagnostic_payload(payload: dict, contract: DeferredIdentityContract, *, source_run_id: int, source_run_attempt: int, pr_number: int, source_event_key: str, source_object_id: int, actor_login: str, source_event_created_at: str) -> dict:
    diagnostic = {
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_event_name": contract.source_event_name,
        "source_event_action": contract.source_event_action,
        "source_event_key": source_event_key,
        "pr_number": pr_number,
        contract.object_id_field: source_object_id,
        "source_actor_login": actor_login,
        "source_event_created_at": source_event_created_at,
    }
    for field_name in (
        "source_workflow_file",
        "source_artifact_name",
        "source_commit_id",
        "source_review_state",
        "source_dismissed_at",
    ):
        value = _optional_nonempty_string(payload, field_name)
        if value is not None:
            diagnostic[field_name] = value
    actor_id = payload.get("source_actor_id", payload.get("comment_author_id", payload.get("actor_id")))
    if actor_id is not None:
        diagnostic["source_actor_id"] = actor_id
    if contract.object_id_field == "comment_id":
        diagnostic["source_comment_id"] = source_object_id
    if contract.object_id_field == "review_id":
        diagnostic["source_review_id"] = source_object_id
    return diagnostic


def _build_deferred_identity(payload: dict) -> DeferredArtifactIdentity:
    payload_kind = payload.get("payload_kind")
    if payload_kind is None and payload.get("schema_version") == 2:
        contract = _contract_for_event(payload.get("source_event_name"), payload.get("source_event_action"))
        if contract is not None and contract.payload_kind in {
            DeferredPayloadKind.DEFERRED_COMMENT,
            DeferredPayloadKind.DEFERRED_REVIEW_COMMENT,
        }:
            payload_kind = contract.payload_kind.value
    try:
        resolved_payload_kind = DeferredPayloadKind(str(payload_kind))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Unsupported deferred workflow_run payload") from exc
    return DeferredArtifactIdentity(
        payload_kind=resolved_payload_kind,
        schema_version=int(payload["schema_version"]),
        source_run_id=int(payload["source_run_id"]),
        source_run_attempt=int(payload["source_run_attempt"]),
        source_event_name=str(payload["source_event_name"]),
        source_event_action=str(payload["source_event_action"]),
        source_event_key=str(payload["source_event_key"]),
        pr_number=int(payload["pr_number"]),
    )


def _validate_identity_contract(identity: DeferredArtifactIdentity) -> None:
    contract = _DEFERRED_IDENTITY_CONTRACTS[identity.payload_kind]
    if (
        identity.source_event_name != contract.source_event_name
        or identity.source_event_action != contract.source_event_action
    ):
        raise RuntimeError("Deferred workflow_run payload kind/event mismatch")
    if not identity.source_event_key.startswith(contract.source_event_key_prefix):
        raise RuntimeError("Deferred workflow_run payload source_event_key prefix mismatch")


def _canonical_source_event_key(contract: DeferredIdentityContract, source_object_id: int) -> str:
    return f"{contract.source_event_key_prefix}{source_object_id}"


def _validate_identity_object_key(identity: DeferredArtifactIdentity, source_object_id: int) -> None:
    contract = _DEFERRED_IDENTITY_CONTRACTS[identity.payload_kind]
    if identity.source_event_key != _canonical_source_event_key(contract, source_object_id):
        raise RuntimeError("Deferred workflow_run payload source_event_key object mismatch")


def recover_deferred_payload_identity(payload: object) -> RecoveredDeferredPayloadIdentity:
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload lacks a recoverable diagnostic target")
    source_run_id = _positive_int(payload, "source_run_id")
    source_run_attempt = _positive_int(payload, "source_run_attempt")
    pr_number = _positive_int(payload, "pr_number")
    source_event_name = _nonempty_string(payload, "source_event_name")
    source_event_action = _nonempty_string(payload, "source_event_action")
    contract = _contract_for_event(source_event_name, source_event_action)
    if contract is None:
        raise RuntimeError("Deferred context payload lacks a supported recoverable event kind")
    source_object_id = _positive_int(payload, contract.object_id_field)
    source_event_key = _nonempty_string(payload, "source_event_key")
    if source_event_key != _canonical_source_event_key(contract, source_object_id):
        raise RuntimeError("Deferred context payload source_event_key does not match recoverable object id")
    actor_login = _first_string(payload, contract.actor_fields, "source actor login")
    source_event_created_at = _recoverable_timestamp(payload, contract.timestamp_fields)
    diagnostic_payload = _diagnostic_payload(
        payload,
        contract,
        source_run_id=source_run_id,
        source_run_attempt=source_run_attempt,
        pr_number=pr_number,
        source_event_key=source_event_key,
        source_object_id=source_object_id,
        actor_login=actor_login,
        source_event_created_at=source_event_created_at,
    )
    return RecoveredDeferredPayloadIdentity(
        source_run_id=source_run_id,
        source_run_attempt=source_run_attempt,
        source_event_name=contract.source_event_name,
        source_event_action=contract.source_event_action,
        source_event_key=source_event_key,
        pr_number=pr_number,
        source_object_id=source_object_id,
        actor_login=actor_login,
        source_event_created_at=source_event_created_at,
        diagnostic_payload=diagnostic_payload,
    )


def build_deferred_comment_replay_context(
    payload: DeferredCommentPayload,
    *,
    expected_event_name: str,
    live_comment_endpoint: str,
) -> DeferredCommentReplayContext:
    contract = _contract_for_event(expected_event_name, "created")
    if contract is None or contract.object_id_field != "comment_id":
        raise RuntimeError("Deferred comment artifact event type is not accepted")
    if payload.identity.source_event_key != _canonical_source_event_key(contract, payload.comment_id):
        raise RuntimeError("Deferred comment artifact source_event_key mismatch")
    return DeferredCommentReplayContext(
        payload=payload,
        expected_event_name=expected_event_name,
        live_comment_endpoint=live_comment_endpoint,
    )


def build_deferred_review_replay_context(
    payload: DeferredReviewPayload,
    *,
    expected_event_action: str,
) -> DeferredReviewReplayContext:
    contract = _contract_for_event("pull_request_review", expected_event_action)
    if contract is None or contract.object_id_field != "review_id":
        raise RuntimeError("Deferred review artifact event type is not accepted")
    if payload.identity.source_event_action != expected_event_action:
        raise RuntimeError("Deferred review artifact action mismatch")
    if payload.identity.source_event_key != _canonical_source_event_key(contract, payload.review_id):
        raise RuntimeError(f"Deferred review-{expected_event_action} artifact source_event_key mismatch")
    return DeferredReviewReplayContext(payload=payload)


def _validate_deferred_comment_artifact(payload: dict) -> None:
    if payload.get("schema_version") == 2:
        _validate_legacy_deferred_comment_artifact(payload)
        return
    required = {
        "payload_kind",
        "schema_version",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_body",
        "comment_created_at",
        "comment_author",
        "comment_author_id",
        "comment_user_type",
        "comment_sender_type",
        "comment_performed_via_github_app",
        "issue_author",
        "issue_state",
        "issue_labels",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 3:
        raise RuntimeError("Deferred workflow_run payload schema_version is not accepted")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_body"), str) or not isinstance(payload.get("comment_created_at"), str):
        raise RuntimeError("Deferred comment artifact comment body or timestamp is malformed")
    if not isinstance(payload.get("comment_sender_type"), str) or not payload["comment_sender_type"].strip():
        raise RuntimeError("Deferred comment artifact comment_sender_type must be a non-empty string")
    if payload.get("comment_installation_id") is not None and not isinstance(payload.get("comment_installation_id"), str):
        raise RuntimeError("Deferred comment artifact comment_installation_id must be a string or null")
    if not isinstance(payload.get("comment_performed_via_github_app"), bool):
        raise RuntimeError("Deferred comment artifact comment_performed_via_github_app must be boolean")
    if payload.get("payload_kind") == DeferredPayloadKind.DEFERRED_REVIEW_COMMENT.value:
        source_commit_id = payload.get("source_commit_id")
        if not isinstance(source_commit_id, str) or not source_commit_id.strip():
            raise RuntimeError("Deferred review comment artifact source_commit_id must be a non-empty string")


def _legacy_optional_bool(payload: dict, field_name: str, *, default: bool = False) -> bool:
    if field_name not in payload or payload.get(field_name) is None:
        return default
    value = payload[field_name]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise RuntimeError(f"Deferred legacy comment artifact {field_name} must be boolean")


def _validate_legacy_deferred_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
        "actor_login",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred legacy comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred workflow_run payload schema_version is not accepted")
    if payload.get("source_event_action") != "created" or payload.get("source_event_name") not in {
        "issue_comment",
        "pull_request_review_comment",
    }:
        raise RuntimeError("Deferred legacy comment artifact event type is not accepted")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred legacy comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("source_created_at"), str) or not isinstance(payload.get("source_body_digest"), str):
        raise RuntimeError("Deferred legacy comment artifact timestamp or body digest is malformed")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred legacy comment artifact classification is malformed")
    if not isinstance(payload.get("actor_login"), str) or not payload["actor_login"].strip():
        raise RuntimeError("Deferred legacy comment artifact actor login is unavailable")
    _legacy_optional_bool(payload, "comment_performed_via_github_app")


def _validate_deferred_review_artifact(payload: dict) -> None:
    required = {
        "payload_kind",
        "schema_version",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "review_id",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 3:
        raise RuntimeError("Deferred workflow_run payload schema_version is not accepted")
    if not isinstance(payload.get("review_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review artifact review_id and pr_number must be integers")


def _validate_deferred_review_comment_artifact(payload: dict) -> None:
    _validate_deferred_comment_artifact(payload)


def parse_deferred_context_payload(payload: dict) -> DeferredReviewPayload | DeferredCommentPayload:
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")
    identity = _build_deferred_identity(payload)
    _validate_identity_contract(identity)
    if identity.payload_kind == DeferredPayloadKind.DEFERRED_COMMENT or identity.payload_kind == DeferredPayloadKind.DEFERRED_REVIEW_COMMENT:
        _validate_deferred_review_comment_artifact(payload)
        comment_id = int(payload["comment_id"])
        _validate_identity_object_key(identity, comment_id)
        if identity.schema_version == 2:
            actor_id = payload.get("actor_id")
            try:
                comment_author_id = int(actor_id) if actor_id is not None else 0
            except (TypeError, ValueError):
                comment_author_id = 0
            return DeferredCommentPayload(
                identity=identity,
                comment_id=comment_id,
                comment_body="",
                comment_created_at=str(payload["source_created_at"]),
                comment_author=str(payload["actor_login"]),
                comment_author_id=comment_author_id,
                comment_user_type=str(payload.get("actor_user_type") or "User"),
                comment_sender_type=str(payload.get("actor_sender_type") or "User"),
                comment_installation_id=(str(payload["comment_installation_id"]) if payload.get("comment_installation_id") else None),
                comment_performed_via_github_app=_legacy_optional_bool(payload, "comment_performed_via_github_app"),
                issue_author=str(payload.get("issue_author") or ""),
                issue_state=str(payload.get("issue_state") or "open"),
                issue_labels=tuple(str(label) for label in payload.get("issue_labels", ())),
                raw_payload=payload,
                source_commit_id=(str(payload["source_commit_id"]) if payload.get("source_commit_id") is not None else None),
                source_body_digest=str(payload["source_body_digest"]),
                source_comment_class=str(payload["comment_class"]),
                source_has_non_command_text=bool(payload["has_non_command_text"]),
            )
        if identity.schema_version != 3:
            raise RuntimeError("Deferred workflow_run payload schema_version is not accepted")
        return DeferredCommentPayload(
            identity=identity,
            comment_id=comment_id,
            comment_body=str(payload["comment_body"]),
            comment_created_at=str(payload["comment_created_at"]),
            comment_author=str(payload["comment_author"]),
            comment_author_id=int(payload["comment_author_id"]),
            comment_user_type=str(payload["comment_user_type"]),
            comment_sender_type=str(payload["comment_sender_type"]),
            comment_installation_id=(str(payload["comment_installation_id"]) if payload.get("comment_installation_id") else None),
            comment_performed_via_github_app=payload["comment_performed_via_github_app"],
            issue_author=str(payload["issue_author"]),
            issue_state=str(payload["issue_state"]),
            issue_labels=tuple(str(label) for label in payload["issue_labels"]),
            raw_payload=payload,
            source_commit_id=(str(payload["source_commit_id"]) if payload.get("source_commit_id") is not None else None),
        )
    if identity.payload_kind == DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED or identity.payload_kind == DeferredPayloadKind.DEFERRED_REVIEW_DISMISSED:
        _validate_deferred_review_artifact(payload)
        review_id = int(payload["review_id"])
        _validate_identity_object_key(identity, review_id)
        payload_type = (
            DeferredReviewSubmittedPayload
            if identity.payload_kind == DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED
            else DeferredReviewDismissedPayload
        )
        return payload_type(
            identity=identity,
            review_id=review_id,
            source_submitted_at=(str(payload["source_submitted_at"]) if payload.get("source_submitted_at") is not None else None),
            source_review_state=(str(payload["source_review_state"]) if payload.get("source_review_state") is not None else None),
            source_commit_id=(str(payload["source_commit_id"]) if payload.get("source_commit_id") is not None else None),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    raise RuntimeError("Unsupported deferred workflow_run payload")


def validate_triggering_run_identity(bot, payload: dict) -> None:
    triggering_id = bot.get_config_value("WORKFLOW_RUN_TRIGGERING_ID").strip()
    if triggering_id and str(payload.get("source_run_id")) != triggering_id:
        raise RuntimeError("Deferred artifact run_id mismatch")
    triggering_attempt = bot.get_config_value("WORKFLOW_RUN_TRIGGERING_ATTEMPT").strip()
    if triggering_attempt and str(payload.get("source_run_attempt")) != triggering_attempt:
        raise RuntimeError("Deferred artifact run_attempt mismatch")
    if bot.get_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION").strip() != "success":
        raise RuntimeError("Triggering observer workflow did not conclude successfully")


def validate_workflow_run_artifact_identity(bot, payload: dict) -> None:
    validate_triggering_run_identity(bot, payload)
