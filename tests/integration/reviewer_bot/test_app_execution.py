import json
from pathlib import Path

import pytest

from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state, make_tracked_review_state

pytestmark = pytest.mark.integration


def test_app_harness_exposes_focused_runtime_services(monkeypatch):
    harness = AppHarness(monkeypatch)

    assert harness.state_store is harness.runtime.state_store
    assert harness.locks is harness.runtime.locks
    assert harness.handlers is harness.runtime.handlers
    assert harness.touch_tracker is harness.runtime.touch_tracker


def test_execute_run_reloads_state_before_syncing_status_labels(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")

    initial_state = make_state()
    reloaded_state = make_state()
    load_calls = {"count": 0}
    save_completed = {"value": False}
    sync_inputs = {}
    release_calls = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    def fake_handle_comment_event(state):
        assert state is initial_state
        harness.runtime.collect_touched_item(42)
        return True

    def fake_save_state(state):
        assert state is initial_state
        save_completed["value"] = True
        return True

    def fake_sync_status_labels_for_items(state, issue_numbers):
        sync_inputs["save_completed"] = save_completed["value"]
        sync_inputs["state"] = state
        sync_inputs["issue_numbers"] = list(issue_numbers)
        assert state is reloaded_state
        assert list(issue_numbers) == [42]
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: release_calls.append("released") or True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", fake_handle_comment_event)
    harness.stub_save_state(fake_save_state)
    harness.stub_sync_status_labels(fake_sync_status_labels_for_items)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert load_calls["count"] >= 2
    assert sync_inputs == {
        "save_completed": True,
        "state": reloaded_state,
        "issue_numbers": [42],
    }
    assert release_calls == ["released"]

def test_execute_run_returns_failure_when_save_state_fails(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    harness.stub_save_state(lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is True


def test_execute_run_releases_lock_after_save_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    release_calls = []
    harness.stub_lock(acquire=lambda: None, release=lambda: release_calls.append("released") or True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    harness.stub_save_state(lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert release_calls == ["released"]


def test_execute_run_persists_projection_repair_marker_after_projection_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    initial_state = make_state()
    reloaded_state = make_state()
    make_tracked_review_state(reloaded_state, 42, reviewer="alice")
    load_count = {"value": 0}
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_count["value"] += 1
        if load_count["value"] == 1:
            return initial_state
        return reloaded_state

    def fake_handle_comment_event(state):
        harness.runtime.collect_touched_item(42)
        return True

    def fake_save_state(state):
        saved_states.append(state.copy())
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", fake_handle_comment_event)
    harness.stub_save_state(fake_save_state)
    harness.stub_sync_status_labels(lambda state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert len(saved_states) == 2
    assert saved_states[-1]["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"


def test_execute_run_returns_failure_when_lock_release_fails(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: False)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.release_failed is True

def test_execute_run_returns_failure_for_invalid_workflow_run_context(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="pull_request_review",
        WORKFLOW_RUN_EVENT_ACTION="submitted",
    )
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_workflow_run_event", lambda state: (_ for _ in ()).throw(RuntimeError("invalid deferred context")))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is False


def test_d4a_app_branch_to_phase_map_is_frozen_pre_edit():
    app_text = Path("scripts/reviewer_bot_lib/app.py").read_text(encoding="utf-8")

    assert "if lock_required:" in app_text
    assert "state = bot.state_store.load_state(fail_on_unavailable=lock_required)" in app_text
    assert "state, restored = bot.adapters.workflow.process_pass_until_expirations(state)" in app_text
    assert "state, sync_changes = bot.adapters.workflow.sync_members_with_queue(state)" in app_text
    assert "touched_items = bot.drain_touched_items()" in app_text
    assert '_revalidate_epoch(bot, loaded_epoch, "authoritative save")' in app_text
    assert "if not bot.state_store.save_state(state):" in app_text
    assert "state = bot.state_store.load_state(fail_on_unavailable=True)" in app_text
    assert '_revalidate_epoch(bot, loaded_epoch, "status-label projection")' in app_text
    assert "if _mark_projection_repair_needed(bot, state, touched_items, str(exc)):" in app_text
    assert "if not bot.locks.release():" in app_text


def test_d4b_post_edit_phase_map_matches_pre_edit_transaction_shape():
    pre_map = json.loads(Path("tests/fixtures/equivalence/app/transaction_phase_map.json").read_text(encoding="utf-8"))
    post_map = json.loads(Path("tests/fixtures/equivalence/app/post_edit_transaction_phase_map.json").read_text(encoding="utf-8"))

    assert post_map["harness_id"] == "D4b app post-edit transaction phase map"
    assert post_map["branch_to_phase"] == pre_map["branch_to_phase"]
