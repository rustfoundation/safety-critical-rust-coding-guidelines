"""Packet verification owner for review-state-machine guardrails."""

from scripts.reviewer_bot_core import review_state_machine
from tests.fixtures.reviewer_bot import make_state


def test_owner_ensure_review_entry_upgrades_legacy_rows_and_materializes_sidecars():
    state = {
        **make_state(),
        "last_updated": "2026-03-17T09:00:00Z",
        "active_reviews": {"42": ["alice"]},
    }

    review = review_state_machine.ensure_review_entry(state, 42)

    assert review is not None
    assert state["active_reviews"]["42"] is review
    assert review["skipped"] == ["alice"]
    assert review["sidecars"]["pending_privileged_commands"] == {}
    assert review["sidecars"]["deferred_gaps"] == {}
    assert review["sidecars"]["reconciled_source_events"] == {}


def test_owner_accept_channel_event_dedupes_and_keeps_latest_highest_precedence_record():
    review = {
        "reviewer_comment": {"accepted": None, "seen_keys": []},
    }

    assert review_state_machine.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
        source_precedence=1,
    ) is True
    assert review_state_machine.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
        source_precedence=1,
    ) is False
    assert review_state_machine.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:101",
        timestamp="2026-03-17T09:00:00Z",
        actor="alice",
        source_precedence=2,
    ) is True
    assert review_state_machine.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:102",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
        source_precedence=2,
    ) is True

    channel = review["reviewer_comment"]
    assert channel["seen_keys"] == [
        "issue_comment:100",
        "issue_comment:101",
        "issue_comment:102",
    ]
    assert channel["accepted"]["semantic_key"] == "issue_comment:102"
    assert channel["accepted"]["source_precedence"] == 2


def test_owner_contributor_activity_clears_stale_reviewer_handoff():
    review = {
        "current_cycle_reviewer_handoff": {
            "timestamp": "2026-03-17T10:00:00Z",
            "reviewer": "alice",
        }
    }

    assert review_state_machine.accept_channel_event(
        review,
        "contributor_comment",
        semantic_key="issue_comment:200",
        timestamp="2026-03-17T10:30:00Z",
        actor="dana",
    ) is True

    assert review["current_cycle_reviewer_handoff"] is None


def test_owner_set_current_reviewer_resets_cycle_local_state_without_dropping_sidecars():
    state = make_state()
    review = review_state_machine.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["reviewer_comment"] = {
        "accepted": {"semantic_key": "issue_comment:1", "timestamp": "2026-03-17T10:00:00Z"},
        "seen_keys": ["issue_comment:1"],
    }
    review["current_cycle_completion"] = {"completed": True}
    review["current_cycle_write_approval"] = {"approved": True}
    review["current_cycle_reviewer_handoff"] = {"timestamp": "2026-03-17T10:00:00Z"}
    review["sidecars"]["pending_privileged_commands"]["issue_comment:10"] = {"status": "pending"}

    review_state_machine.set_current_reviewer(
        state,
        42,
        "alice",
        now="2026-03-18T09:00:00+00:00",
        assignment_method="manual",
    )

    assert review["current_reviewer"] == "alice"
    assert review["assignment_method"] == "manual"
    assert review["reviewer_comment"] == {"accepted": None, "seen_keys": []}
    assert review["reviewer_review"] == {"accepted": None, "seen_keys": []}
    assert review["contributor_comment"] == {"accepted": None, "seen_keys": []}
    assert review["current_cycle_completion"] == {}
    assert review["current_cycle_write_approval"] == {}
    assert review["current_cycle_reviewer_handoff"] is None
    assert review["sidecars"]["pending_privileged_commands"] == {
        "issue_comment:10": {"status": "pending"}
    }
