from typing import get_type_hints

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import event_inputs, lease_lock, review_state
from scripts.reviewer_bot_lib.context import ReviewerBotContext
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_render_lock_commit_message_uses_direct_json_import():
    rendered = lease_lock.render_lock_commit_message(reviewer_bot._runtime_bot(), {"lock_state": "unlocked"})
    assert rendered.startswith("reviewer-bot-lock-v1\n")


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


def test_event_inputs_build_manual_dispatch_request_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("MANUAL_ACTION", "preview-reviewer-board")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")

    request = event_inputs.build_manual_dispatch_request(runtime)

    assert request.action == "preview-reviewer-board"
    assert request.issue_number == 42
    assert request.privileged_source_event_key == "issue_comment:100"


def test_event_inputs_build_issue_lifecycle_request_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline"]')
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("SENDER_LOGIN", "alice")
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    runtime.set_config_value("ISSUE_TITLE", "New title")
    runtime.set_config_value("ISSUE_BODY", "new body")
    runtime.set_config_value("ISSUE_CHANGES_TITLE_FROM", "Old title")
    runtime.set_config_value("ISSUE_CHANGES_BODY_FROM", "old body")
    runtime.set_config_value("PR_HEAD_SHA", "head-2")
    runtime.set_config_value("EVENT_CREATED_AT", "2026-03-17T10:05:00Z")

    request = event_inputs.build_issue_lifecycle_request(runtime)

    assert request.issue_number == 42
    assert request.is_pull_request is True
    assert request.issue_labels == ("coding guideline",)
    assert request.issue_author == "dana"
    assert request.sender_login == "alice"
    assert request.updated_at == "2026-03-17T10:00:00Z"
    assert request.issue_title == "New title"
    assert request.issue_body == "new body"
    assert request.previous_title == "Old title"
    assert request.previous_body == "old body"
    assert request.pr_head_sha == "head-2"
    assert request.event_created_at == "2026-03-17T10:05:00Z"


def test_event_inputs_build_label_and_sync_requests_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("LABEL_NAME", "sign-off: create pr")
    runtime.set_config_value("PR_HEAD_SHA", "head-2")
    runtime.set_config_value("EVENT_CREATED_AT", "2026-03-17T10:05:00Z")

    label_request = event_inputs.build_label_event_request(runtime)
    sync_request = event_inputs.build_pull_request_sync_request(runtime)

    assert label_request.issue_number == 42
    assert label_request.is_pull_request is True
    assert label_request.label_name == "sign-off: create pr"
    assert sync_request.issue_number == 42
    assert sync_request.head_sha == "head-2"
    assert sync_request.event_created_at == "2026-03-17T10:05:00Z"
