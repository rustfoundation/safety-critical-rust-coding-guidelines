import json
from pathlib import Path

from scripts.reviewer_bot_lib import app
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def _load_phase_map() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/app/transaction_phase_map.json").read_text(
            encoding="utf-8"
        )
    )


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


def test_d4a_transaction_phase_map_fixture_exists_and_lists_all_required_phases():
    phase_map = _load_phase_map()

    assert phase_map["harness_id"] == "D4a app transaction phase map"
    assert phase_map["phases"] == [
        "lock acquisition",
        "initial load",
        "pass-until restoration",
        "member sync",
        "event handling",
        "touched-item drain",
        "schedule-only empty-active-reviews guard",
        "authoritative-save epoch revalidation",
        "authoritative save",
        "reload before status sync",
        "status-sync epoch revalidation",
        "projection failure repair marker persistence",
        "lock release",
    ]


def test_d4b_app_event_intent_classification_remains_explicit_transaction_orchestration():
    app_text = Path("scripts/reviewer_bot_lib/app.py").read_text(encoding="utf-8")

    assert "def _classify_event_intent_from_context(" in app_text
    assert "if event_name == \"issue_comment\":" in app_text
    assert "if event_name == \"workflow_run\":" in app_text
