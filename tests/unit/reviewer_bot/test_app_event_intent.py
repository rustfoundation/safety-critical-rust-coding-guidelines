import json
from pathlib import Path

import pytest

from scripts.reviewer_bot_lib import app
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot_env import set_workflow_run_event_payload


def _load_phase_map() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/app/transaction_phase_map.json").read_text(
            encoding="utf-8"
        )
    )


def test_classify_event_intent_cross_repo_review_is_read_only(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("PR_IS_CROSS_REPOSITORY", "true")
    intent = app.classify_event_intent(runtime, "pull_request_review", "submitted")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_preview_reviewer_board_is_non_mutating(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("MANUAL_ACTION", "preview-reviewer-board")
    intent = app.classify_event_intent(runtime, "workflow_dispatch", "")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_same_repo_review_is_read_only(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review", "submitted")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_same_repo_dismissed_review_is_read_only(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review", "dismissed")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_review_comment_is_non_mutating_defer(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    intent = app.classify_event_intent(runtime, "pull_request_review_comment", "created")
    assert intent == runtime.EVENT_INTENT_NON_MUTATING_DEFER


@pytest.mark.parametrize(
    ("workflow_run_event", "workflow_run_event_action"),
    [
        ("pull_request_review", "submitted"),
        ("pull_request_review", "dismissed"),
        ("issue_comment", "created"),
        ("pull_request_review_comment", "created"),
    ],
)
def test_classify_event_intent_supported_workflow_run_source_action_pairs_are_mutating(
    monkeypatch, workflow_run_event, workflow_run_event_action
):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("REVIEWER_BOT_WORKFLOW_KIND", "reconcile")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    set_workflow_run_event_payload(runtime.config, "Reviewer Bot PR Review Submitted Observer")
    intent = app.classify_event_intent(runtime, "workflow_run", "completed")
    assert intent == runtime.EVENT_INTENT_MUTATING


@pytest.mark.parametrize(
    ("workflow_run_event", "workflow_run_event_action"),
    [
        ("pull_request_review", "edited"),
        ("issue_comment", "deleted"),
        ("pull_request_review_comment", "edited"),
        ("pull_request_review", ""),
        ("workflow_dispatch", "completed"),
    ],
)
def test_classify_event_intent_unsupported_workflow_run_source_action_pairs_are_read_only(
    monkeypatch, workflow_run_event, workflow_run_event_action
):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("REVIEWER_BOT_WORKFLOW_KIND", workflow_run_event)
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION", workflow_run_event_action)

    assert app.classify_event_intent(runtime, "workflow_run", "completed") == runtime.EVENT_INTENT_NON_MUTATING_READONLY


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
