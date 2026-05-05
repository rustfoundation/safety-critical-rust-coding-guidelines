import pytest

from scripts.reviewer_bot_lib import review_state
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reconcile_harness import issue_comment_payload
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


def test_execute_run_closed_issue_comment_safe_noop_keeps_lifecycle_cleanup_owner(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        ISSUE_NUMBER=42,
        IS_PULL_REQUEST="false",
        ISSUE_STATE="closed",
        ISSUE_AUTHOR="dana",
        COMMENT_USER_TYPE="User",
        COMMENT_SENDER_TYPE="User",
        COMMENT_AUTHOR="dana",
        COMMENT_AUTHOR_ID=101,
        COMMENT_ID=100,
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="reviewer-bot validation close-path comment",
        COMMENT_PERFORMED_VIA_GITHUB_APP="false",
    )

    initial_state = make_state()
    review = review_state.ensure_review_entry(initial_state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    reloaded_state = make_state()
    load_calls = {"count": 0}
    save_calls = []
    sync_calls = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_save_state(lambda state: save_calls.append("42" in state["active_reviews"]) or True)
    harness.stub_sync_status_labels(lambda state, issue_numbers: sync_calls.append((state, list(issue_numbers))) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_calls == []
    assert sync_calls == []


def test_execute_run_closed_issue_comment_without_entry_skips_save(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        ISSUE_NUMBER=42,
        IS_PULL_REQUEST="false",
        ISSUE_STATE="closed",
        ISSUE_AUTHOR="dana",
        COMMENT_USER_TYPE="User",
        COMMENT_SENDER_TYPE="User",
        COMMENT_AUTHOR="dana",
        COMMENT_AUTHOR_ID=101,
        COMMENT_ID=100,
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="reviewer-bot validation close-path comment",
        COMMENT_PERFORMED_VIA_GITHUB_APP="false",
    )

    state = make_state()
    save_called = {"value": False}
    sync_calls = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: sync_calls.append(list(issue_numbers)) or False)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_called["value"] is False
    assert sync_calls == []


def test_execute_run_closed_pr_comment_safe_noop_does_not_save_or_project(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        ISSUE_NUMBER=42,
        IS_PULL_REQUEST="true",
        ISSUE_STATE="closed",
        ISSUE_AUTHOR="dana",
        COMMENT_USER_TYPE="User",
        COMMENT_SENDER_TYPE="User",
        COMMENT_AUTHOR="alice",
        COMMENT_AUTHOR_ID=101,
        COMMENT_AUTHOR_ASSOCIATION="MEMBER",
        COMMENT_ID=100,
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="@guidelines-bot /queue",
        COMMENT_PERFORMED_VIA_GITHUB_APP="false",
        REVIEWER_BOT_ROUTE_OUTCOME="trusted_direct",
        REVIEWER_BOT_TRUST_CLASS="pr_trusted_direct",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        PR_HEAD_FULL_NAME="rustfoundation/safety-critical-rust-coding-guidelines",
        PR_AUTHOR="dana",
        GITHUB_RUN_ID="123",
        GITHUB_RUN_ATTEMPT="1",
    )

    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    save_called = {"value": False}
    sync_calls = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: sync_calls.append(list(issue_numbers)) or False)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert state["active_reviews"]["42"] is review
    assert save_called["value"] is False
    assert sync_calls == []


def test_execute_run_late_workflow_run_reconcile_missing_row_records_orphan(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Comment Router")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
        WORKFLOW_RUN_TRIGGERING_ID="610",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
    )
    harness.runtime.stub_deferred_payload(
        issue_comment_payload(
            pr_number=42,
            comment_id=210,
            source_event_key="issue_comment:210",
            body="@guidelines-bot /queue",
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=610,
            source_run_attempt=1,
        )
    )

    state = make_state()
    save_called = {"value": False}
    sync_calls = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_save_state(lambda current: save_called.__setitem__("value", True) or True)
    harness.stub_sync_status_labels(
        lambda current, issue_numbers: sync_calls.append(list(issue_numbers)) or False
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    assert state["active_reviews"] == {}
    assert state["sidecars"]["orphaned_deferred_reconcile_events"]["issue_comment:210"]["recovery_status"] == "orphaned_deferred_event"
    assert save_called["value"] is True
    assert sync_calls == [[42]]
