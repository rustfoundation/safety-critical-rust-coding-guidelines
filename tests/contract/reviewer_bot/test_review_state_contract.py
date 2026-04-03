from pathlib import Path

import pytest

from scripts.reviewer_bot_lib import review_state, reviews
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.contract


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


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


def test_review_state_module_exposes_named_mutation_surface():
    for name in [
        "ensure_review_entry",
        "accept_channel_event",
        "record_reviewer_activity",
        "record_transition_notice_sent",
        "set_current_reviewer",
        "update_reviewer_activity",
        "mark_review_complete",
        "get_current_cycle_boundary",
    ]:
        assert hasattr(review_state, name)


def test_production_modules_do_not_import_mutable_review_state_api_from_reviews_module():
    review_state_text = _read("scripts/reviewer_bot_lib/review_state.py")
    runtime_text = _read("scripts/reviewer_bot_lib/runtime.py")
    bootstrap_text = _read("scripts/reviewer_bot_lib/bootstrap_runtime.py")
    commands_text = _read("scripts/reviewer_bot_lib/commands.py")
    reconcile_text = _read("scripts/reviewer_bot_lib/reconcile.py")
    reviews_text = _read("scripts/reviewer_bot_lib/reviews.py")

    for name in [
        "ensure_review_entry",
        "accept_channel_event",
        "record_reviewer_activity",
        "record_transition_notice_sent",
        "set_current_reviewer",
        "update_reviewer_activity",
        "mark_review_complete",
        "get_current_cycle_boundary",
    ]:
        assert f"def {name}(" in review_state_text
        assert f"from .reviews import {name}" not in runtime_text
        assert f"reviews.{name}(" not in runtime_text
        assert f"reviews.{name}(" not in bootstrap_text
        assert f"bot.{name}(" not in commands_text
        assert f"bot.{name}(" not in reconcile_text
        assert f"bot.{name}(" not in reviews_text


def test_reviews_module_no_longer_exposes_public_mutation_helpers():
    for name in [
        "ensure_review_entry",
        "accept_channel_event",
        "record_reviewer_activity",
        "record_transition_notice_sent",
        "set_current_reviewer",
        "update_reviewer_activity",
        "mark_review_complete",
        "get_current_cycle_boundary",
    ]:
        assert hasattr(reviews, name) is False
