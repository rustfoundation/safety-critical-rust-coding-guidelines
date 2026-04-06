import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.contract

from scripts.reviewer_bot_lib import reconcile


def _load_fixture_payload(relative_path: str) -> dict:
    data = json.loads(Path(relative_path).read_text(encoding="utf-8"))
    return data["payload"]


@pytest.mark.parametrize(
    ("workflow_path", "artifact_name", "payload_name"),
    [
        (
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-comment.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-submitted.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-dismissed.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-comment.json",
        ),
    ],
)
def test_observer_workflow_files_match_expected_artifact_contract(
    workflow_path, artifact_name, payload_name
):
    workflow = __import__("yaml").safe_load(Path(workflow_path).read_text(encoding="utf-8"))
    build_step = workflow["jobs"]["observer"]["steps"][0]
    upload_step = workflow["jobs"]["observer"]["steps"][1]

    assert build_step["env"]["PAYLOAD_PATH"] == "${{ runner.temp }}/" + payload_name
    assert upload_step["with"]["name"] == artifact_name
    assert upload_step["with"]["path"] == "${{ runner.temp }}/" + payload_name

@pytest.mark.parametrize(
    ("payload", "workflow_name", "workflow_file", "artifact_name", "payload_name"),
    [
        (
            {
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_run_id": 1,
                "source_run_attempt": 2,
            },
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-1-attempt-2",
            "deferred-comment.json",
        ),
        (
            {
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_run_id": 1,
                "source_run_attempt": 2,
            },
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-1-attempt-2",
            "deferred-review-submitted.json",
        ),
        (
            {
                "source_event_name": "pull_request_review",
                "source_event_action": "dismissed",
                "source_run_id": 1,
                "source_run_attempt": 2,
            },
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-1-attempt-2",
            "deferred-review-dismissed.json",
        ),
        (
            {
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_run_id": 1,
                "source_run_attempt": 2,
            },
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-1-attempt-2",
            "deferred-review-comment.json",
        ),
    ],
)
def test_deferred_workflow_identity_helpers_match_expected_contract(
    payload,
    workflow_name,
    workflow_file,
    artifact_name,
    payload_name,
):
    assert reconcile._expected_observer_identity(payload) == (
        workflow_name,
        workflow_file,
    )
    assert reconcile._artifact_expected_name(payload) == artifact_name
    assert reconcile._artifact_expected_payload_name(payload) == payload_name


@pytest.mark.parametrize(
    ("fixture_path", "artifact_name", "payload_name"),
    [
        (
            "tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json",
            "reviewer-bot-comment-context-401-attempt-3",
            "deferred-comment.json",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            "reviewer-bot-review-submitted-context-402-attempt-4",
            "deferred-review-submitted.json",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            "reviewer-bot-review-dismissed-context-403-attempt-5",
            "deferred-review-dismissed.json",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            "reviewer-bot-review-comment-context-404-attempt-6",
            "deferred-review-comment.json",
        ),
    ],
)
def test_frozen_workflow_payload_fixtures_match_exact_artifact_identity_contract(
    fixture_path, artifact_name, payload_name
):
    payload = _load_fixture_payload(fixture_path)

    assert payload["source_artifact_name"] == artifact_name
    assert reconcile._artifact_expected_name(payload) == artifact_name
    assert reconcile._artifact_expected_payload_name(payload) == payload_name

def test_validate_workflow_run_artifact_identity_rejects_triggering_name_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Wrong Workflow")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    bot = SimpleNamespace(get_config_value=lambda name, default="": __import__("os").environ.get(name, default))

    with pytest.raises(RuntimeError, match="Triggering workflow name mismatch"):
        reconcile._validate_workflow_run_artifact_identity(bot, payload)

def test_validate_workflow_run_artifact_identity_rejects_run_attempt_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    bot = SimpleNamespace(get_config_value=lambda name, default="": __import__("os").environ.get(name, default))

    with pytest.raises(RuntimeError, match="run_attempt mismatch"):
        reconcile._validate_workflow_run_artifact_identity(bot, payload)

def test_validate_workflow_run_artifact_identity_requires_successful_conclusion(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "failure")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    bot = SimpleNamespace(get_config_value=lambda name, default="": __import__("os").environ.get(name, default))

    with pytest.raises(RuntimeError, match="did not conclude successfully"):
        reconcile._validate_workflow_run_artifact_identity(bot, payload)
