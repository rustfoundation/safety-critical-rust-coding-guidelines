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


def test_execute_run_preview_issue314_state_health_is_read_only_and_inspects_active_rows(
    monkeypatch,
    capsys,
):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-preview",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="999",
        GITHUB_RUN_ATTEMPT="4",
        STATE_ISSUE_NUMBER=314,
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
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["preview_action"] == "preview-issue314-state-health"
    assert payload["state_issue_number"] == 314
    assert payload["issue_number"] == 314
    assert payload["active_review_row_count"] == 1
    assert payload["active_rows_inspected"] == [264]
    assert payload["rows_operator_action_required"] == [264]
    assert payload["rows_blocked"] == []
    assert payload["pr264_no_ping_status"] == "pass"
    assert payload["lock_attempted"] is False
    assert payload["state_save_attempted"] is False
    assert payload["tracked_state_mutations_attempted"] is False
    assert payload["touched_projection_attempted"] is False
    assert payload["artifact_name"] == "reviewer-bot-preview-output-999-attempt-4"
    assert payload["artifact_file"] == "preview-output.json"
    assert payload["output_keys"] == sorted(payload.keys())


def test_execute_run_preview_issue314_state_health_blocks_unavailable_live_rows(
    monkeypatch,
    capsys,
):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-preview",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1000",
        GITHUB_RUN_ATTEMPT="1",
        STATE_ISSUE_NUMBER=314,
    )
    state = make_state()
    make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/264",
        status_code=502,
        payload={"message": "bad gateway"},
    ).add_request(
        "GET",
        "issues/264/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["active_rows_inspected"] == [264]
    assert payload["rows_blocked"] == [264]
    assert payload["row_inventory"][0]["blockers"] == [
        "live_snapshot_unavailable",
        "reviewer_response_unavailable",
        "status_projection_unavailable",
    ]


def test_execute_run_preview_issue314_state_health_keeps_aligned_awaiting_reviewer_response_healthy(
    monkeypatch,
    capsys,
):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-preview",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1001",
        GITHUB_RUN_ATTEMPT="1",
        STATE_ISSUE_NUMBER=314,
    )

    state = make_state()
    review = make_tracked_review_state(
        state,
        410,
        reviewer="cpetig",
        assigned_at="2026-01-01T00:00:00Z",
        active_cycle_started_at="2026-01-01T00:00:00Z",
    )
    review["active_head_sha"] = "head-live"
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/410",
        status_code=200,
        payload={
            "number": 410,
            "state": "open",
            "pull_request": {},
            "labels": [{"name": "status: awaiting reviewer response"}],
        },
    ).add_request(
        "GET",
        "pulls/410",
        status_code=200,
        payload={
            **pull_request_payload(410, head_sha="head-live", author="contributor"),
            "requested_reviewers": [{"login": "cpetig"}],
        },
    ).add_pull_request_reviews(410, []).add_request(
        "GET",
        "issues/410/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["active_rows_inspected"] == [410]
    assert payload["rows_blocked"] == []
    assert payload["rows_repairable"] == []
    row = payload["row_inventory"][0]
    assert row["health_classification"] == "healthy"
    assert row["automated_reminder_risk"] is False
    assert row["status_label_risk"] == "aligned"
