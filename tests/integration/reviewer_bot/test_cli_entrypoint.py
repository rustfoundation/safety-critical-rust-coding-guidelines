import pytest

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration


def test_main_show_state_uses_direct_yaml_import(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="show-state",
    )
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())

    run = harness.run_main()

    assert run.exit_code is None
    output = capsys.readouterr().out
    assert "Current state:" in output
    assert "freshness_runtime_epoch" in output


def test_main_builds_event_context_for_preview_wrapper(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
    )
    captured = harness.stub_execute_run(
        reviewer_bot.ExecutionResult(exit_code=0, state_changed=False)
    )

    run = harness.run_main()

    assert run.exit_code is None
    assert captured.context is not None
    assert captured.context.event_name == "workflow_dispatch"
    assert captured.context.event_action == ""
    assert captured.context.manual_action == "preview-reviewer-board"


def test_main_builds_workflow_run_context_before_execution(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="pull_request_review",
        WORKFLOW_RUN_EVENT_ACTION="dismissed",
    )
    captured = harness.stub_execute_run(
        reviewer_bot.ExecutionResult(exit_code=0, state_changed=False)
    )

    run = harness.run_main()

    assert run.exit_code is None
    assert captured.context is not None
    assert captured.context.event_name == "workflow_run"
    assert captured.context.event_action == "completed"
    assert captured.context.workflow_run_event == "pull_request_review"
    assert captured.context.workflow_run_event_action == "dismissed"


def test_main_exits_with_nonzero_execution_result(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
    )
    captured = harness.stub_execute_run(
        reviewer_bot.ExecutionResult(exit_code=1, state_changed=False)
    )

    run = harness.run_main()

    assert run.exit_code == 1
    assert captured.context is not None
    assert captured.context.event_name == "issue_comment"
    assert captured.context.event_action == "created"


def test_main_accepts_explicit_runtime_argument(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
    )
    captured = harness.stub_execute_run(
        reviewer_bot.ExecutionResult(exit_code=0, state_changed=False)
    )

    try:
        reviewer_bot.main(harness.runtime)
    except SystemExit as exc:  # pragma: no cover - defensive
        pytest.fail(f"unexpected SystemExit: {exc.code}")

    assert captured.context is not None
    assert captured.context.event_name == "issue_comment"
    assert captured.context.event_action == "created"


def test_app_harness_no_longer_requires_singleton_runtime_patch(monkeypatch):
    AppHarness(monkeypatch)

    assert hasattr(reviewer_bot, "RUNTIME") is False
