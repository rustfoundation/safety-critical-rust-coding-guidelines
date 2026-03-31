from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


def test_execute_run_closed_issue_comment_cleanup_persists_removed_review_entry(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation close-path comment")

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

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda state: save_calls.append("42" in state["active_reviews"]) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda state, issue_numbers: sync_calls.append((state, list(issue_numbers))) or True,
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_calls == [False]
    assert len(sync_calls) == 1
    assert sync_calls[0][0] is reloaded_state
    assert sync_calls[0][1] == [42]


def test_execute_run_closed_issue_comment_without_entry_skips_save(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation close-path comment")

    state = make_state()
    save_called = {"value": False}
    sync_calls = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_called.__setitem__("value", True) or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: sync_calls.append(list(issue_numbers)) or False,
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_called["value"] is False
    assert sync_calls == [[42]]
