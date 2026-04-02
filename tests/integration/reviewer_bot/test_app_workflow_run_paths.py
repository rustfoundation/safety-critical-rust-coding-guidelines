import pytest

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


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
        return reviewer_bot.LeaseContext(
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
    harness.stub_handler("handle_workflow_run_event", lambda state: False)

    harness.run_execute()

    assert acquire_called["value"] is True

def test_execute_run_workflow_run_review_comment_reconcile_acquires_lock(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="workflow_run", EVENT_ACTION="completed", WORKFLOW_RUN_EVENT="pull_request_review_comment")

    acquire_called = {"value": False}

    def fake_acquire():
        acquire_called["value"] = True
        return reviewer_bot.LeaseContext(
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
    harness.stub_handler("handle_workflow_run_event", lambda state: False)

    harness.run_execute()

    assert acquire_called["value"] is True
