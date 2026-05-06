import json
from datetime import timedelta

import pytest

from scripts.reviewer_bot_lib import maintenance
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import (
    iso_z,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_builders import accept_reviewer_review
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_execute_run_preview_check_overdue_uses_frozen_pr264_operational_projection(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-check-overdue",
        ISSUE_NUMBER=264,
        VALIDATION_NONCE="nonce-pr264",
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
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["preview_action"] == "preview-check-overdue"
    assert payload["issue_number"] == 264
    assert payload["validation_nonce"] == "nonce-pr264"
    assert payload["evaluated_repo"] == "rustfoundation/safety-critical-rust-coding-guidelines"
    assert payload["head_sha"] == "workflow-head"
    assert payload["evaluated_ref"] == "workflow-head"
    assert payload["workflow_path"] == ".github/workflows/reviewer-bot-preview.yml"
    assert payload["run_id"] == "777"
    assert payload["run_attempt"] == "2"
    assert payload["artifact_name"] == "reviewer-bot-preview-output-777-attempt-2"
    assert payload["artifact_file"] == "preview-output.json"
    assert payload["output_keys"] == sorted(payload.keys())
    assert payload["response_state"] == "reviewer_reassignment_needed"
    assert payload["reviewer_authority_outcome"] == "tracked_reviewer_confirmed"
    assert payload["suppression_reason"] == "legacy_duplicate_reminders_exhausted"
    assert payload["current_scope_key"] == "reviewer=iglesias|head=head-live|cycle=2026-02-10T17:20:07Z|anchor=2026-02-10T17:20:07Z"
    assert payload["current_scope_basis"] == "active_cycle_started_at"
    assert payload["would_post_warning"] is False
    assert payload["would_post_transition"] is False
    assert payload["lock_attempted"] is False
    assert payload["state_save_attempted"] is False
    assert payload["tracked_state_mutations_attempted"] is False
    assert payload["touched_projection_attempted"] is False


def test_execute_run_preview_check_overdue_backfills_claim_cycle_from_assignment_guidance(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-check-overdue",
        ISSUE_NUMBER=264,
        VALIDATION_NONCE="nonce-pr264-claim",
        GITHUB_SHA="workflow-head",
    )

    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-26T04:58:03.401345+00:00",
    )
    review["assignment_method"] = "claim"
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
            "labels": [],
            "created_at": "2025-12-08T04:16:34Z",
        },
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
    ).add_request(
        "GET",
        "issues/264/comments?per_page=100&page=1",
        status_code=200,
        payload=[
            {
                "user": {"login": "github-actions"},
                "created_at": "2026-02-10T17:20:07Z",
                "body": "👋 Hey @iglesias! You've been assigned to review this coding guideline PR.\n\n## Your Role as Reviewer",
            }
        ],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current_scope_key"] == "reviewer=iglesias|head=head-live|cycle=2026-02-26T04:58:03.401345+00:00|anchor=2026-02-26T04:58:03.401345+00:00"
    assert payload["current_scope_basis"] == "assigned_at"
    assert payload["suppression_reason"] == "review_head_stale"
    assert payload["would_post_warning"] is True
    assert payload["would_post_transition"] is False


def test_preview_check_overdue_matches_real_overdue_scope_and_posting_decision(monkeypatch, capsys):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-check-overdue",
        ISSUE_NUMBER=42,
        VALIDATION_NONCE="nonce-42",
        GITHUB_SHA="workflow-head",
    )

    state = make_state()
    now = harness.runtime.datetime.now(harness.runtime.timezone.utc)
    anchor_timestamp = iso_z(now - timedelta(days=harness.runtime.REVIEW_DEADLINE_DAYS + 1))
    make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at=anchor_timestamp,
        active_cycle_started_at=anchor_timestamp,
    )

    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/42",
        status_code=200,
        payload={"number": 42, "state": "open", "pull_request": {}, "labels": []},
    ).add_request(
        "GET",
        "pulls/42",
        status_code=200,
        payload={
            **pull_request_payload(42, head_sha="head-1", author="dana"),
            "requested_reviewers": [{"login": "alice"}],
            "labels": [],
        },
    ).add_pull_request_reviews(42, []).add_request(
        "GET",
        "issues/42/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_lock(acquire=lambda: (_ for _ in ()).throw(AssertionError("preview should not acquire lock")))
    harness.stub_pass_until(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip pass-until processing")))
    harness.stub_sync_members(lambda current: (_ for _ in ()).throw(AssertionError("preview should skip member sync")))
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("preview should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("preview should not sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    overdue = maintenance.check_overdue_reviews(harness.runtime, state)

    assert payload["response_state"] == "awaiting_reviewer_response"
    assert payload["suppression_reason"] == "no_reviewer_activity"
    assert payload["current_scope_basis"] == "active_cycle_started_at"
    assert payload["current_scope_key"] == f"reviewer=alice|head=head-1|cycle={anchor_timestamp}|anchor={anchor_timestamp}"
    assert payload["would_post_warning"] is True
    assert payload["would_post_transition"] is False
    assert overdue == [
        {
            "issue_number": 42,
            "reviewer": "alice",
            "days_overdue": 1,
            "days_since_warning": 0,
            "needs_warning": True,
            "needs_transition": False,
            "anchor_reason": "no_reviewer_activity",
            "anchor_timestamp": anchor_timestamp,
            "current_scope_key": f"reviewer=alice|head=head-1|cycle={anchor_timestamp}|anchor={anchor_timestamp}",
            "current_scope_basis": "active_cycle_started_at",
        }
    ]
