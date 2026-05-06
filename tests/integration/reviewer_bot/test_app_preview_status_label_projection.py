import json

import pytest

from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_builders import accept_reviewer_review
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_execute_run_preview_status_label_projection_is_read_only_pr264_contract(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-status-label-projection",
        ISSUE_NUMBER=264,
        VALIDATION_NONCE="nonce-pr264-projection",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="777",
        GITHUB_RUN_ATTEMPT="2",
    )

    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:77",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/264",
        status_code=200,
        payload={
            "number": 264,
            "state": "open",
            "pull_request": {},
            "labels": [{"name": "status: awaiting reviewer response"}],
        },
    ).add_request(
        "GET",
        "pulls/264",
        status_code=200,
        payload={
            **pull_request_payload(264, head_sha="head-live", author="manhatsu"),
            "requested_reviewers": [],
        },
    ).add_pull_request_reviews(
        264,
        [
            review_payload(
                501,
                state="APPROVED",
                submitted_at="2026-03-18T12:10:42Z",
                commit_id="head-live",
                author="plaindocs",
            )
        ],
    ).add_request(
        "GET",
        "issues/264/comments?per_page=100&page=1",
        status_code=200,
        payload=[
            {
                "id": 9001,
                "user": {"login": "github-actions[bot]"},
                "created_at": "2026-04-13T00:44:23Z",
                "body": "⚠️ **Review Reminder**\n\ntransition period",
            },
            {
                "id": 9002,
                "user": {"login": "github-actions[bot]"},
                "created_at": "2026-04-14T00:44:23Z",
                "body": "⚠️ **Review Reminder**\n\ntransition period",
            },
        ],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["preview_action"] == "preview-status-label-projection"
    assert payload["response_state"] == "reviewer_reassignment_needed"
    assert payload["reviewer_authority_outcome"] == "tracked_reviewer_confirmed"
    assert payload["suppression_reason"] == "legacy_duplicate_reminders_exhausted"
    assert payload["current_scope_basis"] == "reminder_cadence_exhausted"
    assert payload["actual_status_labels"] == ["status: awaiting reviewer response"]
    assert payload["desired_status_labels"] == ["status: reviewer reassignment needed"]
    assert payload["labels_to_add"] == ["status: reviewer reassignment needed"]
    assert payload["labels_to_remove"] == ["status: awaiting reviewer response"]
    assert payload["projection_metadata"]["source"] == "reviewer_response_decision"
    assert payload["lock_attempted"] is False
    assert payload["state_save_attempted"] is False
    assert payload["tracked_state_mutations_attempted"] is False
    assert payload["touched_projection_attempted"] is False
    assert payload["artifact_name"] == "reviewer-bot-preview-output-777-attempt-2"
    assert payload["artifact_file"] == "preview-output.json"
    assert payload["output_keys"] == sorted(payload.keys())
