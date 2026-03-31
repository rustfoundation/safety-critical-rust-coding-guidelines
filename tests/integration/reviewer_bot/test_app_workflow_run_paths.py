from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


def test_execute_run_cross_repo_review_does_not_acquire_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fail_if_called)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert acquire_called["value"] is False


def test_execute_run_same_repo_review_does_not_acquire_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fail_if_called)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert acquire_called["value"] is False


def test_execute_run_workflow_run_reconcile_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")

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

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fake_acquire)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_workflow_run_event", lambda state: False)

    reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert acquire_called["value"] is True


def test_execute_run_workflow_run_review_comment_reconcile_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")

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

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fake_acquire)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_workflow_run_event", lambda state: False)

    reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert acquire_called["value"] is True
