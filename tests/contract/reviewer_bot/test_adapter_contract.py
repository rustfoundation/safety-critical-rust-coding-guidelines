from typing import get_type_hints

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.context import (
    AppEventContextRuntime,
    AppExecutionRuntime,
    GitHubTransportContext,
    LeaseLockContext,
    ReviewerBotContext,
    StateStoreContext,
)
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def test_reviewer_bot_exports_runtime_modules():
    assert reviewer_bot.requests is not None
    assert reviewer_bot.sys is not None
    assert reviewer_bot.datetime is not None
    assert reviewer_bot.timezone is not None

def test_reviewer_bot_satisfies_runtime_context_protocol():
    assert isinstance(reviewer_bot, ReviewerBotContext)

def test_reviewer_bot_satisfies_narrower_lock_and_state_protocols():
    assert isinstance(reviewer_bot, GitHubTransportContext)
    assert isinstance(reviewer_bot, StateStoreContext)
    assert isinstance(reviewer_bot, LeaseLockContext)


def test_reviewer_bot_satisfies_app_specific_runtime_protocols():
    assert isinstance(reviewer_bot, AppEventContextRuntime)
    assert isinstance(reviewer_bot, AppExecutionRuntime)

def test_render_lock_commit_message_uses_direct_json_import():
    rendered = reviewer_bot.render_lock_commit_message({"lock_state": "unlocked"})
    assert reviewer_bot.LOCK_COMMIT_MARKER in rendered

def test_maybe_record_head_observation_repair_wrapper_exports_structured_result_type():
    hints = get_type_hints(reviewer_bot.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult

def test_runtime_context_protocol_exposes_structured_head_repair_contract():
    hints = get_type_hints(ReviewerBotContext.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult

def test_runtime_bot_returns_concrete_runtime_object():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReviewerBotRuntime)
    assert runtime.EVENT_INTENT_MUTATING == reviewer_bot.EVENT_INTENT_MUTATING


def test_fake_runtime_satisfies_app_execution_runtime_protocol(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)

def test_build_event_context_returns_structured_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')

    context = reviewer_bot.build_event_context()

    assert isinstance(context, reviewer_bot.EventContext)
    assert context.event_name == "workflow_run"
    assert context.workflow_run_event == "pull_request_review"
    assert context.issue_labels == ("coding guideline",)

def test_execute_run_returns_execution_result(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: {"active_reviews": {}})
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert isinstance(result, reviewer_bot.ExecutionResult)
    assert result.exit_code == 0
