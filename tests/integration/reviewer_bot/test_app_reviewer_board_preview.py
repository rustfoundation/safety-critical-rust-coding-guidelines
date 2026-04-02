import pytest

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state, valid_reviewer_board_metadata

pytestmark = pytest.mark.integration


def test_execute_run_preview_reviewer_board_disabled_is_clean_noop(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="false",
    )

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda state: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda state, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    output = capsys.readouterr().out
    assert "Reviewer board preview skipped: reviewer board is disabled." in output

def test_execute_run_preview_reviewer_board_missing_token_fails_clearly(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert "REVIEWER_BOARD_TOKEN not set" in capsys.readouterr().err

def test_execute_run_preview_reviewer_board_invalid_manifest_fails_clearly(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
        REVIEWER_BOARD_TOKEN="board-token",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    monkeypatch.setattr(
        harness.runtime,
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

    result = harness.run_execute()

    assert result.exit_code == 1
    assert "Missing reviewer board field: Review State" in capsys.readouterr().err

def test_execute_run_preview_reviewer_board_is_read_only(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
        REVIEWER_BOARD_TOKEN="board-token",
        ISSUE_NUMBER=42,
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"

    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    monkeypatch.setattr(harness.runtime, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []}

    result = harness.run_execute()

    assert result.exit_code == 0
    output = capsys.readouterr().out
    assert "classification: open_tracked_assigned" in output
    assert "ensure_membership: true" in output
