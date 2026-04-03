from typing import get_type_hints

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import lease_lock, review_state
from scripts.reviewer_bot_lib.context import (
    AppEventContextRuntime,
    AppExecutionRuntime,
    ReviewerBotContext,
)
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_runtime_bot_returns_concrete_runtime_object():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReviewerBotRuntime)
    assert runtime.EVENT_INTENT_MUTATING == reviewer_bot._runtime_bot().EVENT_INTENT_MUTATING


def test_runtime_object_satisfies_runtime_context_protocols():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)


def test_render_lock_commit_message_uses_direct_json_import():
    rendered = lease_lock.render_lock_commit_message(reviewer_bot._runtime_bot(), {"lock_state": "unlocked"})
    assert rendered.startswith("reviewer-bot-lock-v1\n")


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

    assert context.event_name == "workflow_run"
    assert context.workflow_run_event == "pull_request_review"
    assert context.issue_labels == ("coding guideline",)


def test_execute_run_returns_execution_result(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    runtime = reviewer_bot._runtime_bot()
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: {"active_reviews": {}})
    monkeypatch.setattr(runtime.handlers, "handle_pull_request_review_event", lambda state: False)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0


def test_review_state_owner_exports_mutation_helper():
    hints = get_type_hints(review_state.ensure_review_entry)

    assert hints["return"] == dict | None


def test_runtime_head_repair_contract_is_runtime_scoped():
    hints = get_type_hints(ReviewerBotContext.maybe_record_head_observation_repair)

    assert hints["return"].__name__ == "HeadObservationRepairResult"


def test_runtime_review_state_adapter_mutates_active_reviews():
    state = make_state()
    review = reviewer_bot._runtime_bot().ensure_review_entry(state, 42, create=True)

    assert review is state["active_reviews"]["42"]
