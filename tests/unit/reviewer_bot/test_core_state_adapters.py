from scripts.reviewer_bot_core import state_adapters
from tests.fixtures.reviewer_bot import make_state


def test_review_entry_adapter_round_trips_full_current_mutation_shape():
    persisted = {
        "skipped": ["alice"],
        "current_reviewer": "bob",
        "cycle_started_at": "2026-03-17T09:00:00Z",
        "active_cycle_started_at": "2026-03-17T09:00:00Z",
        "assigned_at": "2026-03-17T09:00:00Z",
        "active_head_sha": "head-1",
        "last_reviewer_activity": "2026-03-17T10:00:00Z",
        "transition_warning_sent": "2026-03-18T00:00:00Z",
        "transition_notice_sent_at": "2026-03-19T00:00:00Z",
        "assignment_method": "round-robin",
        "review_completed_at": "2026-03-20T00:00:00Z",
        "review_completed_by": "bob",
        "review_completion_source": "unit-test",
        "mandatory_approver_required": True,
        "mandatory_approver_label_applied_at": "2026-03-20T01:00:00Z",
        "mandatory_approver_pinged_at": "2026-03-20T02:00:00Z",
        "mandatory_approver_satisfied_by": "carol",
        "mandatory_approver_satisfied_at": "2026-03-20T03:00:00Z",
        "overdue_anchor": None,
        "reviewer_comment": {
            "accepted": {
                "semantic_key": "issue_comment:10",
                "timestamp": "2026-03-17T10:00:00Z",
                "actor": "alice",
                "reviewed_head_sha": None,
                "source_precedence": 1,
                "payload": {"kind": "comment"},
            },
            "seen_keys": ["issue_comment:10"],
        },
        "reviewer_review": {
            "accepted": {
                "semantic_key": "pull_request_review:11",
                "timestamp": "2026-03-17T11:00:00Z",
                "actor": "bob",
                "reviewed_head_sha": "head-1",
                "source_precedence": 2,
                "payload": {"kind": "review"},
            },
            "seen_keys": ["pull_request_review:11"],
        },
        "contributor_comment": {"accepted": None, "seen_keys": []},
        "contributor_revision": {"accepted": None, "seen_keys": []},
        "review_dismissal": {
            "accepted": {
                "semantic_key": "pull_request_review_dismissed:12",
                "timestamp": "2026-03-18T11:00:00Z",
            },
            "seen_keys": ["pull_request_review_dismissed:12"],
        },
        "current_cycle_completion": {
            "completed": True,
            "completed_at": "2026-03-20T00:00:00Z",
            "source": "unit-test",
            "reviewer": "bob",
        },
        "current_cycle_write_approval": {"approved": False},
    }

    adapted = state_adapters.review_entry_from_persisted(persisted)

    assert adapted is not None
    assert state_adapters.review_entry_to_persisted(adapted) == persisted


def test_review_entry_adapter_matches_current_sparse_upgrade_semantics():
    adapted = state_adapters.review_entry_from_persisted(["alice", "bob"])

    assert adapted is not None
    assert state_adapters.review_entry_to_persisted(adapted) == {
        "skipped": ["alice", "bob"],
        "current_reviewer": None,
        "cycle_started_at": None,
        "active_cycle_started_at": None,
        "assigned_at": None,
        "active_head_sha": None,
        "last_reviewer_activity": None,
        "transition_warning_sent": None,
        "transition_notice_sent_at": None,
        "assignment_method": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "mandatory_approver_required": False,
        "mandatory_approver_label_applied_at": None,
        "mandatory_approver_pinged_at": None,
        "mandatory_approver_satisfied_by": None,
        "mandatory_approver_satisfied_at": None,
        "overdue_anchor": None,
        "reviewer_comment": {"accepted": None, "seen_keys": []},
        "reviewer_review": {"accepted": None, "seen_keys": []},
        "contributor_comment": {"accepted": None, "seen_keys": []},
        "contributor_revision": {"accepted": None, "seen_keys": []},
        "review_dismissal": {"accepted": None, "seen_keys": []},
        "current_cycle_completion": {},
        "current_cycle_write_approval": {},
    }


def test_review_entry_adapter_returns_none_for_unusable_persisted_shape():
    state = make_state()
    state["active_reviews"]["42"] = "broken"

    assert state_adapters.review_entry_from_persisted(state["active_reviews"]["42"]) is None
