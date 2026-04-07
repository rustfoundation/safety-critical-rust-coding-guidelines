from pathlib import Path

import pytest

from scripts.reviewer_bot_lib import reconcile
from scripts.reviewer_bot_lib.context import LeaseContext
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


D4C_DELETION_MANIFEST = []


def test_execute_run_cross_repo_review_does_not_acquire_lock(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="pull_request_review", EVENT_ACTION="submitted", PR_IS_CROSS_REPOSITORY="true")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    harness.stub_lock(acquire=fail_if_called)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_handler("handle_pull_request_review_event", lambda state: False)

    harness.run_execute()

    assert acquire_called["value"] is False

def test_execute_run_same_repo_review_does_not_acquire_lock(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="pull_request_review", EVENT_ACTION="submitted")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    harness.stub_lock(acquire=fail_if_called)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_pull_request_review_event", lambda state: False)

    harness.run_execute()

    assert acquire_called["value"] is False

def test_execute_run_workflow_run_reconcile_acquires_lock(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="workflow_run", EVENT_ACTION="completed", WORKFLOW_RUN_EVENT="pull_request_review")

    acquire_called = {"value": False}

    def fake_acquire():
        acquire_called["value"] = True
        return LeaseContext(
            lock_token="token",
            lock_owner_run_id="run",
            lock_owner_workflow="workflow",
            lock_owner_job="job",
            state_issue_url="https://example.com/issues/314",
            lock_ref="refs/heads/reviewer-bot-state-lock",
            lock_expires_at="2999-01-01T00:00:00+00:00",
        )

    harness.stub_lock(acquire=fake_acquire, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    monkeypatch.setattr(
        reconcile,
        "handle_workflow_run_event_result",
        lambda bot, state: reconcile.WorkflowRunHandlerResult(False, [], False, None, False, False),
    )

    result = harness.run_execute()

    assert acquire_called["value"] is True
    assert result.exit_code == 0

def test_execute_run_workflow_run_review_comment_reconcile_acquires_lock(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="workflow_run", EVENT_ACTION="completed", WORKFLOW_RUN_EVENT="pull_request_review_comment")

    acquire_called = {"value": False}

    def fake_acquire():
        acquire_called["value"] = True
        return LeaseContext(
            lock_token="token",
            lock_owner_run_id="run",
            lock_owner_workflow="workflow",
            lock_owner_job="job",
            state_issue_url="https://example.com/issues/314",
            lock_ref="refs/heads/reviewer-bot-state-lock",
            lock_expires_at="2999-01-01T00:00:00+00:00",
        )

    harness.stub_lock(acquire=fake_acquire, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    monkeypatch.setattr(
        reconcile,
        "handle_workflow_run_event_result",
        lambda bot, state: reconcile.WorkflowRunHandlerResult(False, [], False, None, False, False),
    )

    result = harness.run_execute()

    assert acquire_called["value"] is True
    assert result.exit_code == 0


def test_d4a_phase_map_records_workflow_run_and_non_mutating_branches_explicitly():
    with open("tests/fixtures/equivalence/app/transaction_phase_map.json", encoding="utf-8") as handle:
        phase_map = __import__("json").load(handle)

    assert phase_map["branch_to_phase"]["issues/pull_request_target/issue_comment/workflow_dispatch/schedule/workflow_run dispatch"] == "event handling"
    assert phase_map["branch_to_phase"]["locks.release"] == "lock release"


def test_d4c_deletion_manifest_is_explicit_and_remaining_app_branches_stay_transactional():
    app_text = Path("scripts/reviewer_bot_lib/app.py").read_text(encoding="utf-8")

    assert D4C_DELETION_MANIFEST == []
    assert 'if event_name == "issues":' in app_text
    assert 'elif event_name == "pull_request_target":' in app_text
    assert 'elif event_name == "workflow_run":' in app_text
    assert 'if state_changed or sync_changes or restored:' in app_text
    assert 'if touched_items:' in app_text
    assert 'if projection_failure is not None:' in app_text


def test_m1_typed_workflow_run_result_keeps_public_bool_entrypoint_present():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")

    assert "def handle_workflow_run_event_result(" in reconcile_text
    assert "def handle_workflow_run_event(bot: ReconcileWorkflowRuntimeContext, state: dict) -> bool:" in reconcile_text
    assert "return handle_workflow_run_event_result(bot, state).state_changed" in reconcile_text
