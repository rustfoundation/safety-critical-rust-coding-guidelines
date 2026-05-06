from scripts.reviewer_bot_lib.reconcile_payloads import (
    DeferredArtifactIdentity,
    DeferredPayloadKind,
    DeferredReviewDismissedPayload,
    deferred_workflow_source_contract_for_payload_kind,
    derive_deferred_artifact_source_authority,
    parse_deferred_context_payload,
)


def _identity() -> DeferredArtifactIdentity:
    return DeferredArtifactIdentity(
        payload_kind=DeferredPayloadKind.DEFERRED_REVIEW_SUBMITTED,
        schema_version=3,
        source_run_id=10,
        source_run_attempt=1,
        source_event_name="pull_request_review",
        source_event_action="submitted",
        source_event_key="pull_request_review:20",
        pr_number=264,
    )


def test_deferred_workflow_source_contract_names_submitted_review_owner():
    contract = deferred_workflow_source_contract_for_payload_kind("deferred_review_submitted")

    assert contract.workflow_file == ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml"
    assert "source_commit_id" in contract.required_payload_fields


def test_non_success_identity_is_diagnostic_only_authority():
    authority = derive_deferred_artifact_source_authority(
        _identity(),
        {
            "payload_kind": "deferred_review_submitted",
            "schema_version": 3,
            "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "source_run_id": 10,
            "source_run_attempt": 1,
            "source_artifact_name": "reviewer-bot-review-submitted-context-10-attempt-1",
            "source_event_name": "pull_request_review",
            "source_event_action": "submitted",
            "source_event_key": "pull_request_review:20",
            "pr_number": 264,
            "review_id": 20,
            "source_submitted_at": "2026-04-01T00:00:00Z",
            "source_review_state": "COMMENTED",
            "source_commit_id": "head-a",
            "actor_login": "iglesias",
        },
        triggering_conclusion="failure",
    )

    assert authority.authority_status == "diagnostic_non_success_identity"


def test_deferred_review_dismissed_payload_keeps_canonical_dismissed_at():
    payload = {
        "payload_kind": "deferred_review_dismissed",
        "schema_version": 3,
        "source_workflow_name": "Reviewer Bot PR Review Dismissed Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        "source_run_id": 11,
        "source_run_attempt": 1,
        "source_artifact_name": "reviewer-bot-review-dismissed-context-11-attempt-1",
        "source_event_name": "pull_request_review",
        "source_event_action": "dismissed",
        "source_event_key": "pull_request_review_dismissed:20",
        "pr_number": 264,
        "review_id": 20,
        "source_dismissed_at": "2026-04-01T00:10:00Z",
    }
    contract = deferred_workflow_source_contract_for_payload_kind("deferred_review_dismissed")

    parsed = parse_deferred_context_payload(payload)
    authority = derive_deferred_artifact_source_authority(
        parsed.identity,
        payload,
        triggering_conclusion="success",
        contract=contract,
    )

    assert isinstance(parsed, DeferredReviewDismissedPayload)
    assert parsed.source_dismissed_at == "2026-04-01T00:10:00Z"
    assert parsed.raw_payload["source_dismissed_at"] == "2026-04-01T00:10:00Z"
    assert authority.authority_status == "trusted_exact_identity"
