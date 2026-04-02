import pytest

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


def test_execute_run_closed_issue_comment_cleanup_persists_removed_review_entry(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        ISSUE_NUMBER=42,
        IS_PULL_REQUEST="false",
        ISSUE_STATE="closed",
        ISSUE_AUTHOR="dana",
        COMMENT_USER_TYPE="User",
        COMMENT_AUTHOR="dana",
        COMMENT_ID=100,
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="reviewer-bot validation close-path comment",
    )

    initial_state = make_state()
    review = reviewer_bot.ensure_review_entry(initial_state, 42, create=True)
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
    assert save_calls == [False]
    assert len(sync_calls) == 1
    assert sync_calls[0][0] is reloaded_state
    assert sync_calls[0][1] == [42]

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
        COMMENT_AUTHOR="dana",
        COMMENT_ID=100,
        COMMENT_CREATED_AT="2026-03-17T10:00:00Z",
        COMMENT_BODY="reviewer-bot validation close-path comment",
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
    assert sync_calls == [[42]]
