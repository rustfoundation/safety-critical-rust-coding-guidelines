from dataclasses import fields, is_dataclass

from scripts.reviewer_bot_core import review_state_types


def test_core_review_state_types_are_limited_to_c1_mutation_scope():
    assert is_dataclass(review_state_types.AcceptedChannelRecord)
    assert is_dataclass(review_state_types.DismissalAcceptedRecord)
    assert is_dataclass(review_state_types.ReviewChannelState)
    assert is_dataclass(review_state_types.ReviewEntryState)

    assert [field.name for field in fields(review_state_types.ReviewChannelState)] == [
        "accepted",
        "seen_keys",
    ]
    assert [field.name for field in fields(review_state_types.ReviewEntryState)] == [
        "skipped",
        "current_reviewer",
        "cycle_started_at",
        "active_cycle_started_at",
        "assigned_at",
        "active_head_sha",
        "last_reviewer_activity",
        "transition_warning_sent",
        "transition_notice_sent_at",
        "assignment_method",
        "review_completed_at",
        "review_completed_by",
        "review_completion_source",
        "mandatory_approver_required",
        "mandatory_approver_label_applied_at",
        "mandatory_approver_pinged_at",
        "mandatory_approver_satisfied_by",
        "mandatory_approver_satisfied_at",
        "overdue_anchor",
        "reviewer_comment",
        "reviewer_review",
        "contributor_comment",
        "contributor_revision",
        "review_dismissal",
        "current_cycle_completion",
        "current_cycle_write_approval",
    ]


def test_core_review_state_types_preserve_current_sparse_and_precedence_shapes():
    entry = review_state_types.ReviewEntryState()

    assert entry.skipped == []
    assert entry.mandatory_approver_required is False
    assert entry.current_cycle_completion == {}
    assert entry.current_cycle_write_approval == {}
    assert entry.reviewer_comment.seen_keys == []

    accepted = review_state_types.AcceptedChannelRecord(
        semantic_key="issue_comment:10",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=2,
        payload={"kind": "comment"},
    )
    dismissed = review_state_types.DismissalAcceptedRecord(
        semantic_key="pull_request_review_dismissed:11",
        timestamp="2026-03-17T11:00:00Z",
    )

    entry.reviewer_comment.accepted = accepted
    entry.review_dismissal.accepted = dismissed

    assert entry.reviewer_comment.accepted.source_precedence == 2
    assert entry.review_dismissal.accepted.semantic_key == "pull_request_review_dismissed:11"


def test_core_review_state_types_document_current_persisted_mapping_scope():
    module_doc = review_state_types.__doc__ or ""
    entry_doc = review_state_types.ReviewEntryState.__doc__ or ""

    assert "review-entry initialization and defaulting" in module_doc
    assert "channel-event acceptance and semantic-key tracking" in module_doc
    assert "reviewer activity updates" in module_doc
    assert "completion marking" in module_doc
    assert "cycle-boundary behavior" in module_doc
    assert "do not model deferred-gap diagnosis" in module_doc or "do not model" in module_doc
    assert "persisted review entry fields" in entry_doc
