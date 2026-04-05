"""Deferred reconcile payload and identity helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeferredArtifactIdentity:
    schema_version: int
    source_workflow_name: str
    source_workflow_file: str
    source_run_id: int
    source_run_attempt: int
    source_event_name: str
    source_event_action: str
    source_event_key: str


@dataclass(frozen=True)
class DeferredReviewPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    review_id: int
    source_submitted_at: str | None
    source_review_state: str | None
    source_commit_id: str | None
    actor_login: str | None
    raw_payload: dict


@dataclass(frozen=True)
class DeferredCommentPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    comment_id: int
    comment_class: str
    has_non_command_text: bool
    source_body_digest: str
    source_created_at: str
    actor_login: str | None
    raw_payload: dict


@dataclass(frozen=True)
class ObserverNoopPayload:
    identity: DeferredArtifactIdentity
    pr_number: int
    reason: str
    raw_payload: dict


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
        return self.payload.pr_number

    @property
    def actor_login(self) -> str:
        return self.payload.actor_login or ""

    @property
    def source_created_at(self) -> str:
        return self.payload.source_created_at

    @property
    def source_freshness_eligible(self) -> bool:
        return self.payload.comment_class in {"plain_text", "command_plus_text"} and self.payload.has_non_command_text


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
        return self.payload.pr_number

    @property
    def actor_login(self) -> str:
        return self.payload.actor_login or ""


def _build_deferred_identity(payload: dict) -> DeferredArtifactIdentity:
    return DeferredArtifactIdentity(
        schema_version=int(payload["schema_version"]),
        source_workflow_name=str(payload["source_workflow_name"]),
        source_workflow_file=str(payload["source_workflow_file"]),
        source_run_id=int(payload["source_run_id"]),
        source_run_attempt=int(payload["source_run_attempt"]),
        source_event_name=str(payload["source_event_name"]),
        source_event_action=str(payload["source_event_action"]),
        source_event_key=str(payload["source_event_key"]),
    )


def build_deferred_comment_replay_context(
    payload: DeferredCommentPayload,
    *,
    expected_event_name: str,
    live_comment_endpoint: str,
) -> DeferredCommentReplayContext:
    if payload.identity.source_event_key != f"{expected_event_name}:{payload.comment_id}":
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
    expected_prefix = "pull_request_review:" if expected_event_action == "submitted" else "pull_request_review_dismissed:"
    if payload.identity.source_event_action != expected_event_action:
        raise RuntimeError("Deferred review artifact action mismatch")
    if payload.identity.source_event_key != f"{expected_prefix}{payload.review_id}":
        raise RuntimeError(f"Deferred review-{expected_event_action} artifact source_event_key mismatch")
    return DeferredReviewReplayContext(payload=payload)


def _validate_deferred_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
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
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred comment artifact source digest or timestamp is malformed")


def _validate_deferred_review_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
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
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("review_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review artifact review_id and pr_number must be integers")


def _validate_deferred_review_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
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
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review-comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review-comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review-comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred review-comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred review-comment artifact source digest or timestamp is malformed")


def _validate_observer_noop_payload(payload: dict) -> None:
    required = {
        "schema_version",
        "kind",
        "reason",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Observer no-op payload missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 1:
        raise RuntimeError("Observer no-op payload schema_version is not accepted")
    if payload.get("kind") != "observer_noop":
        raise RuntimeError("Observer no-op payload kind mismatch")
    if not isinstance(payload.get("reason"), str) or not payload.get("reason"):
        raise RuntimeError("Observer no-op payload reason must be a non-empty string")
    if not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Observer no-op payload pr_number must be an integer")


def parse_deferred_context_payload(payload: dict) -> DeferredReviewPayload | DeferredCommentPayload | ObserverNoopPayload:
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")

    if payload.get("kind") == "observer_noop":
        _validate_observer_noop_payload(payload)
        return ObserverNoopPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            reason=str(payload["reason"]),
            raw_payload=payload,
        )

    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        _validate_deferred_comment_artifact(payload)
        return DeferredCommentPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            comment_id=int(payload["comment_id"]),
            comment_class=str(payload["comment_class"]),
            has_non_command_text=bool(payload["has_non_command_text"]),
            source_body_digest=str(payload["source_body_digest"]),
            source_created_at=str(payload["source_created_at"]),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    if event_name == "pull_request_review_comment" and event_action == "created":
        _validate_deferred_review_comment_artifact(payload)
        return DeferredCommentPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            comment_id=int(payload["comment_id"]),
            comment_class=str(payload["comment_class"]),
            has_non_command_text=bool(payload["has_non_command_text"]),
            source_body_digest=str(payload["source_body_digest"]),
            source_created_at=str(payload["source_created_at"]),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    if event_name == "pull_request_review" and event_action in {"submitted", "dismissed"}:
        _validate_deferred_review_artifact(payload)
        return DeferredReviewPayload(
            identity=_build_deferred_identity(payload),
            pr_number=int(payload["pr_number"]),
            review_id=int(payload["review_id"]),
            source_submitted_at=(str(payload["source_submitted_at"]) if payload.get("source_submitted_at") is not None else None),
            source_review_state=(str(payload["source_review_state"]) if payload.get("source_review_state") is not None else None),
            source_commit_id=(str(payload["source_commit_id"]) if payload.get("source_commit_id") is not None else None),
            actor_login=(str(payload["actor_login"]) if payload.get("actor_login") is not None else None),
            raw_payload=payload,
        )
    raise RuntimeError("Unsupported deferred workflow_run payload")


def expected_observer_identity(payload: dict) -> tuple[str, str]:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return (
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "submitted":
        return (
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "dismissed":
        return (
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        )
    if event_name == "pull_request_review_comment" and event_action == "created":
        return (
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
        )
    raise RuntimeError("Unsupported deferred workflow identity")


def artifact_expected_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    run_id = payload.get("source_run_id")
    run_attempt = payload.get("source_run_attempt")
    if event_name == "issue_comment" and event_action == "created":
        return f"reviewer-bot-comment-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "submitted":
        return f"reviewer-bot-review-submitted-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return f"reviewer-bot-review-dismissed-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review_comment" and event_action == "created":
        return f"reviewer-bot-review-comment-context-{run_id}-attempt-{run_attempt}"
    raise RuntimeError("Unsupported deferred artifact naming")


def artifact_expected_payload_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return "deferred-comment.json"
    if event_name == "pull_request_review" and event_action == "submitted":
        return "deferred-review-submitted.json"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return "deferred-review-dismissed.json"
    if event_name == "pull_request_review_comment" and event_action == "created":
        return "deferred-review-comment.json"
    raise RuntimeError("Unsupported deferred payload path")
