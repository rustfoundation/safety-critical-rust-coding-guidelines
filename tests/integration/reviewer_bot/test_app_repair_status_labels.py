import json

import pytest

from scripts.reviewer_bot_lib import app
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


def test_execute_run_targeted_status_label_repair_does_not_broaden_epoch_repair(
    monkeypatch,
    tmp_path,
):
    harness = AppHarness(monkeypatch)
    repair_summary_path = tmp_path / "repair" / "repair-summary.json"
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="repair-review-status-labels",
        ISSUE_NUMBER=264,
        VALIDATION_NONCE="nonce-pr264-repair",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="888",
        GITHUB_RUN_ATTEMPT="3",
    )
    harness.stub_lock()
    monkeypatch.setenv("REPAIR_SUMMARY_PATH", str(repair_summary_path))

    state = make_state(epoch="freshness_v15")
    state["status_projection_epoch"] = "stale_projection_epoch"
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
    ).add_request(
        "POST",
        "labels",
        status_code=422,
        payload={"message": "already_exists"},
    ).add_request(
        "DELETE",
        "issues/264/labels/status%3A%20awaiting%20reviewer%20response",
        status_code=204,
        payload=None,
    ).add_request(
        "POST",
        "issues/264/labels",
        status_code=200,
        payload={"labels": ["status: reviewer reassignment needed"]},
    )
    harness.runtime.github.stub(routes)
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("targeted repair should not save epoch state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("targeted repair should not enter broad sync")))
    monkeypatch.setattr(
        app,
        "collect_status_projection_repair_items",
        lambda bot, state: (_ for _ in ()).throw(AssertionError("targeted repair broadened")),
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(repair_summary_path.read_text(encoding="utf-8"))
    assert payload["repair_action"] == "repair-review-status-labels"
    assert payload["issue_number"] == 264
    assert payload["issue_numbers"] == [264]
    assert payload["target_collection_mode"] == "issue_scoped"
    assert payload["labels_added"] == ["status: reviewer reassignment needed"]
    assert payload["labels_removed"] == ["status: awaiting reviewer response"]
    assert payload["artifact_name"] == "reviewer-bot-repair-output-888-attempt-3"
    assert payload["artifact_file"] == "repair-summary.json"
    assert payload["output_keys"] == sorted(payload.keys())
    assert state["status_projection_epoch"] == "stale_projection_epoch"
