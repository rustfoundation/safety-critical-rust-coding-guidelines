from scripts.reviewer_bot_lib import app
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def test_classify_event_intent_cross_repo_review_is_non_mutating_defer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("PR_IS_CROSS_REPOSITORY", "true")
    intent = app.classify_event_intent(runtime, "pull_request_review", "submitted")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_preview_reviewer_board_is_non_mutating(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("MANUAL_ACTION", "preview-reviewer-board")
    intent = app.classify_event_intent(runtime, "workflow_dispatch", "")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_same_repo_review_is_non_mutating_defer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review", "submitted")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_same_repo_dismissed_review_is_non_mutating_defer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review", "dismissed")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_review_comment_is_non_mutating_defer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review_comment", "created")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_workflow_run_dismissed_review_is_mutating(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("WORKFLOW_RUN_EVENT", "pull_request_review")
    runtime.set_config_value("WORKFLOW_RUN_EVENT_ACTION", "dismissed")
    intent = app.classify_event_intent(runtime, "workflow_run", "completed")
    assert intent == runtime.EVENT_INTENT_MUTATING


def test_classify_event_intent_treats_supported_workflow_run_sources_as_mutating(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("WORKFLOW_RUN_EVENT", "issue_comment")
    assert app.classify_event_intent(runtime, "workflow_run", "completed") == runtime.EVENT_INTENT_MUTATING
    runtime.set_config_value("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    assert app.classify_event_intent(runtime, "workflow_run", "completed") == runtime.EVENT_INTENT_MUTATING
