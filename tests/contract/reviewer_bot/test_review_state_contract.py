import pytest

from scripts.reviewer_bot_lib import review_state
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.contract


def test_ensure_review_entry_initializes_tracked_review_shape():
    state = make_state()

    review = review_state.ensure_review_entry(state, 42, create=True)

    assert review is not None
    assert review["current_reviewer"] is None
    assert review["reviewer_comment"]["accepted"] is None
    assert review["pending_privileged_commands"] == {}


def test_accept_channel_event_deduplicates_semantic_keys():
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None

    first = review_state.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    second = review_state.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )

    assert first is True
    assert second is False


def test_mark_review_complete_updates_completion_fields():
    state = make_state()
    review_state.ensure_review_entry(state, 42, create=True)

    changed = review_state.mark_review_complete(state, 42, "alice", "unit-test")

    assert changed is True
    review = state["active_reviews"]["42"]
    assert review["review_completed_by"] == "alice"
    assert review["review_completion_source"] == "unit-test"
    assert review["current_cycle_completion"]["completed"] is True


def test_list_open_tracked_review_items_returns_only_assigned_entries():
    state = make_state()
    review_state.ensure_review_entry(state, 42, create=True)
    review_state.ensure_review_entry(state, 99, create=True)
    state["active_reviews"]["42"]["current_reviewer"] = "alice"

    assert review_state.list_open_tracked_review_items(state) == [42]
