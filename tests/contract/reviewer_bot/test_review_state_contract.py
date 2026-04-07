from pathlib import Path

import pytest

from scripts.reviewer_bot_core import state_adapters
from scripts.reviewer_bot_lib import review_state, reviews
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.contract


ROOT = Path(__file__).resolve().parents[3]

DELETED_REVIEW_MUTATION_SYMBOLS = [
    "_ensure_channel_map",
    "_ensure_dict",
    "_ensure_review_entry",
    "_reset_cycle_state",
    "clear_transition_timers",
    "_record_reviewer_activity",
    "_record_transition_notice_sent",
    "_set_current_reviewer",
    "_semantic_key_seen",
    "_accept_channel_event",
    "_update_reviewer_activity",
    "_mark_review_complete",
    "_get_current_cycle_boundary",
    "_legacy_accept_reviewer_review_from_live_review",
    "_legacy_refresh_reviewer_review_from_live_preferred_review",
    "_legacy_repair_missing_reviewer_review_state",
]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_state_contract_table() -> str:
    return _read("tests/fixtures/state_contracts/review_state_contract_table.md")


def _read_review_state_inventory() -> str:
    return _read("tests/fixtures/equivalence/review_state/api_inventory.md")


def test_ensure_review_entry_initializes_tracked_review_shape():
    state = make_state()

    review = review_state.ensure_review_entry(state, 42, create=True)

    assert review is not None
    assert review["current_reviewer"] is None
    assert review["reviewer_comment"]["accepted"] is None
    assert review["pending_privileged_commands"] == {}
    assert review["observer_discovery_watermarks"] == {}
    assert review["current_cycle_write_approval"] == {}


def test_state_contract_table_fixture_lists_frozen_sections_and_field_classifications():
    table = _read_state_contract_table()

    for heading in [
        "Top-Level Persisted Keys",
        "Per-Review-Entry Keys",
        "Per-Channel Keys",
        "Lazy-Upgrade Cases",
    ]:
        assert heading in table

    for line in [
        "- active_reviews: required",
        "- status_projection_epoch: lazily materialized",
        "- pending_privileged_commands: lazily materialized",
        "- current_cycle_write_approval: lazily materialized",
        "- observer_discovery_watermarks: lazily materialized",
        "- reconciled_source_events: tolerated legacy shape",
        "- accepted: lazily materialized",
        "- seen_keys: tolerated legacy shape",
        "- non-list skipped: tolerated legacy shape",
    ]:
        assert line in table


def test_ensure_review_entry_lazily_upgrades_sparse_legacy_review_entries():
    state = make_state()
    state["active_reviews"]["42"] = ["alice", "bob"]

    review = review_state.ensure_review_entry(state, 42, create=False)

    assert review is state["active_reviews"]["42"]
    assert review["skipped"] == ["alice", "bob"]
    assert review["reviewer_comment"] == {"accepted": None, "seen_keys": []}
    assert review["pending_privileged_commands"] == {}
    assert review["reconciled_source_events"] == []


def test_ensure_review_entry_repairs_missing_nested_maps_and_legacy_list_fields():
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": "legacy",
        "reviewer_comment": {"accepted": None, "seen_keys": "bad"},
        "reconciled_source_events": "bad",
    }

    review = review_state.ensure_review_entry(state, 42, create=False)

    assert review is not None
    assert review["skipped"] == []
    assert review["reviewer_comment"] == {"accepted": None, "seen_keys": []}
    assert review["contributor_revision"] == {"accepted": None, "seen_keys": []}
    assert review["deferred_gaps"] == {}
    assert review["observer_discovery_watermarks"] == {}
    assert review["pending_privileged_commands"] == {}
    assert review["current_cycle_completion"] == {}
    assert review["current_cycle_write_approval"] == {}
    assert review["reconciled_source_events"] == []


def test_core_state_adapter_matches_current_sparse_review_entry_upgrade_contract():
    state = make_state()
    state["active_reviews"]["42"] = ["alice", "bob"]

    adapted = state_adapters.review_entry_from_persisted(state["active_reviews"]["42"])
    upgraded = review_state.ensure_review_entry(state, 42, create=False)

    assert adapted is not None
    assert state_adapters.review_entry_to_persisted(adapted) == {
        key: upgraded[key]
        for key in state_adapters.review_entry_to_persisted(adapted)
    }


def test_review_state_mutation_inventory_freezes_overlap_classification_and_live_read_scope():
    inventory = _read_review_state_inventory()

    for heading in [
        "Local-State-Only Mutation APIs",
        "Live-Read-Assisted Mutation APIs",
        "Read-Only Helpers",
    ]:
        assert heading in inventory

    for line in [
        "- ensure_review_entry: local-state-only mutation",
        "- accept_channel_event: local-state-only mutation",
        "- record_reviewer_activity: local-state-only mutation",
        "- record_transition_notice_sent: local-state-only mutation",
        "- set_current_reviewer: local-state-only mutation",
        "- update_reviewer_activity: local-state-only mutation",
        "- mark_review_complete: local-state-only mutation",
        "- get_current_cycle_boundary: read-only helper",
        "- clear_transition_timers: local-state-only mutation",
        "- semantic_key_seen: read-only helper",
        "- accept_reviewer_review_from_live_review: live-read-assisted mutation; C1c in-scope",
        "- refresh_reviewer_review_from_live_preferred_review: live-read-assisted mutation; C1c in-scope",
        "- repair_missing_reviewer_review_state: live-read-assisted mutation; C1c in-scope",
        "- list_open_tracked_review_items: read-only helper",
    ]:
        assert line in inventory


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


def test_review_state_local_mutation_surface_delegates_to_core_owner():
    review_state_text = _read("scripts/reviewer_bot_lib/review_state.py")

    assert "from scripts.reviewer_bot_core import review_state_live_repair, review_state_machine" in review_state_text
    assert "return review_state_machine.ensure_review_entry(state, issue_number, create=create)" in review_state_text
    assert "return review_state_machine.accept_channel_event(" in review_state_text
    assert "return review_state_machine.mark_review_complete(state, issue_number, reviewer, source)" in review_state_text


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


def test_runtime_and_bootstrap_forwarders_are_explicit_adapter_compatibility_surface_only():
    runtime_text = _read("scripts/reviewer_bot_lib/runtime.py")
    bootstrap_text = _read("scripts/reviewer_bot_lib/bootstrap_runtime.py")

    assert "Adapter-only mutable review-state compatibility surface." in runtime_text
    assert "Adapter-only mutable review-state compatibility surface." in bootstrap_text
    assert "record_transition_notice_sent" not in runtime_text
    assert "accept_channel_event" not in runtime_text
    assert "get_current_cycle_boundary" not in runtime_text
    assert "record_transition_notice_sent" not in bootstrap_text
    assert "accept_channel_event" not in bootstrap_text
    assert "get_current_cycle_boundary" not in bootstrap_text


def test_tests_do_not_rely_on_runtime_mutable_review_state_forwarders_outside_contract_surface():
    for path in ROOT.glob("tests/**/*.py"):
        if path.name in {"test_fake_runtime_contract.py", "test_adapter_contract.py", "test_review_state_contract.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "runtime.ensure_review_entry" not in text
        assert "runtime.set_current_reviewer" not in text
        assert "runtime.update_reviewer_activity" not in text
        assert "runtime.mark_review_complete" not in text


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


def test_c1d_deletion_manifest_matches_deleted_duplicate_review_mutation_logic():
    reviews_text = _read("scripts/reviewer_bot_lib/reviews.py")

    for symbol in DELETED_REVIEW_MUTATION_SYMBOLS:
        assert f"def {symbol}(" not in reviews_text


def test_c1d_repo_wide_importer_and_caller_inventory_for_deleted_review_mutation_logic_is_zero():
    importer_inventory = []
    caller_inventory = []

    for path in ROOT.glob("**/*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path == "tests/contract/reviewer_bot/test_review_state_contract.py":
            continue
        text = path.read_text(encoding="utf-8")
        for symbol in DELETED_REVIEW_MUTATION_SYMBOLS:
            if (
                f"from .reviews import {symbol}" in text
                or f"from scripts.reviewer_bot_lib.reviews import {symbol}" in text
            ):
                importer_inventory.append((relative_path, symbol))
            if f"reviews.{symbol}(" in text:
                caller_inventory.append((relative_path, symbol))

    assert importer_inventory == []
    assert caller_inventory == []
