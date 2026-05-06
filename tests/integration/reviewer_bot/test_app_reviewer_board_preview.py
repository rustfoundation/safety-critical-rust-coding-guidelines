import json

import pytest

from scripts.reviewer_bot_lib import review_state
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
    valid_reviewer_board_metadata,
)
from tests.fixtures.reviewer_bot_builders import accept_reviewer_review
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_execute_run_preview_reviewer_board_disabled_is_clean_noop(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="false",
    )

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda state: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda state, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    output = capsys.readouterr().out
    assert "Reviewer board preview skipped: reviewer board is disabled." in output

def test_execute_run_preview_reviewer_board_missing_token_fails_clearly(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda state: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))

    result = harness.run_execute()

    assert result.exit_code == 1
    captured = capsys.readouterr().err
    assert "REVIEWER_BOARD_TOKEN not set" in captured or any(
        "REVIEWER_BOARD_TOKEN not set" in record["message"]
        for record in harness.runtime.logger.records
    )

def test_execute_run_preview_reviewer_board_invalid_manifest_fails_clearly(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
        REVIEWER_BOARD_TOKEN="board-token",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    monkeypatch.setattr(
        harness.runtime,
        "github_graphql",
        lambda query, variables=None, *, token=None: {
            "data": {
                "organization": {
                    "projectV2": {
                        "id": "PVT_kwDOB",
                        "title": "Reviewer Board",
                        "fields": {"nodes": []},
                    }
                }
            }
        },
    )

    result = harness.run_execute()

    assert result.exit_code == 1
    captured = capsys.readouterr().err
    assert "Missing reviewer board field: Review State" in captured or any(
        "Missing reviewer board field: Review State" in record["message"]
        for record in harness.runtime.logger.records
    )

def test_execute_run_preview_reviewer_board_is_read_only(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
        REVIEWER_BOARD_TOKEN="board-token",
        ISSUE_NUMBER=42,
        VALIDATION_NONCE="board-preview-42",
        GITHUB_SHA="workflow-head",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

    state = make_state()
    state["status_projection_epoch"] = "status_projection_v1"
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-05-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-05-20T12:34:56Z"

    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    monkeypatch.setattr(harness.runtime, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []}
    harness.runtime.github.get_issue_or_pr_snapshot_result = lambda issue_number: GitHubApiResult(
        200,
        {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    harness.runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["preview_action"] == "preview-reviewer-board"
    assert payload["issue_number"] == 42
    assert payload["validation_nonce"] == "board-preview-42"
    assert payload["head_sha"] == "workflow-head"
    assert payload["board_attention"] == "No"
    assert payload["board_waiting_since"] == "2026-05-20"
    assert payload["lock_attempted"] is False
    assert payload["state_save_attempted"] is False
    assert payload["tracked_state_mutations_attempted"] is False
    assert payload["touched_projection_attempted"] is False


def test_execute_run_preview_reviewer_board_keeps_pr264_alternate_approval_projection(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-reviewer-board",
        REVIEWER_BOARD_ENABLED="true",
        REVIEWER_BOARD_TOKEN="board-token",
        ISSUE_NUMBER=264,
        VALIDATION_NONCE="board-preview-pr264",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1004",
        GITHUB_RUN_ATTEMPT="1",
    )
    monkeypatch.setattr(harness.runtime, "_reviewer_board_project_metadata", None, raising=False)

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
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-04-01T00:00:00Z"

    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/264",
        status_code=200,
        payload={"number": 264, "state": "open", "pull_request": {}, "labels": []},
    ).add_request(
        "GET",
        "pulls/264",
        status_code=200,
        payload={
            **pull_request_payload(264, head_sha="head-live", author="manhatsu"),
            "requested_reviewers": [],
            "labels": [],
        },
    ).add_pull_request_reviews(
        264,
        [review_payload(501, state="APPROVED", submitted_at="2026-03-18T12:10:42Z", commit_id="head-live", author="plaindocs")],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    monkeypatch.setattr(harness.runtime, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["preview_action"] == "preview-reviewer-board"
    assert payload["issue_number"] == 264
    assert payload["validation_nonce"] == "board-preview-pr264"
    assert payload["evaluated_repo"] == "rustfoundation/safety-critical-rust-coding-guidelines"
    assert payload["head_sha"] == "workflow-head"
    assert payload["evaluated_ref"] == "workflow-head"
    assert payload["workflow_path"] == ".github/workflows/reviewer-bot-preview.yml"
    assert payload["run_id"] == "1004"
    assert payload["run_attempt"] == "1"
    assert payload["artifact_name"] == "reviewer-bot-preview-output-1004-attempt-1"
    assert payload["artifact_file"] == "preview-output.json"
    assert payload["response_state"] == "reviewer_reassignment_needed"
    assert payload["reviewer_authority_outcome"] == "tracked_reviewer_confirmed"
    assert payload["suppression_reason"] == "transition_notice_sent"
    assert payload["current_scope_key"] == "reviewer=iglesias|head=head-live|cycle=2026-02-10T17:20:07Z|anchor=2026-02-10T17:20:07Z"
    assert payload["current_scope_basis"] == "reminder_cadence_exhausted"
    assert payload["would_post_warning"] is False
    assert payload["would_post_transition"] is False
    assert payload["lock_attempted"] is False
    assert payload["state_save_attempted"] is False
    assert payload["tracked_state_mutations_attempted"] is False
    assert payload["touched_projection_attempted"] is False
    assert payload["board_attention"] == "Transition Notice Sent"
    assert payload["board_waiting_since"] == "2026-02-10"
    assert payload["output_keys"] == sorted(payload.keys())
