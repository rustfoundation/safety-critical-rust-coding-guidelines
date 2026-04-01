from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state, valid_reviewer_board_metadata
import pytest

pytestmark = pytest.mark.integration

def test_execute_run_preview_reviewer_board_disabled_is_clean_noop(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "false")

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should not save state")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda state, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")),
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    output = capsys.readouterr().out
    assert "Reviewer board preview skipped: reviewer board is disabled." in output

def test_execute_run_preview_reviewer_board_missing_token_fails_clearly(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert "REVIEWER_BOARD_TOKEN not set" in capsys.readouterr().err

def test_execute_run_preview_reviewer_board_invalid_manifest_fails_clearly(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: make_state())
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_graphql",
        lambda query, variables=None, *, token=None: {
            "data": {
                "organization": {
                    "projectV2": {
                        "id": "PVT_kwDOB",
                        "title": "Reviewer Board",
                        "fields": {"nodes": []},
                    }
                }
            }
        },
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 1
    assert "Missing reviewer board field: Review State" in capsys.readouterr().err

def test_execute_run_preview_reviewer_board_is_read_only(monkeypatch, capsys):
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)

    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"

    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        reviewer_bot,
        "acquire_state_issue_lease_lock",
        lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "process_pass_until_expirations",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_members_with_queue",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")),
    )
    monkeypatch.setattr(reviewer_bot, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    output = capsys.readouterr().out
    assert "classification: open_tracked_assigned" in output
    assert "ensure_membership: true" in output
