import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from scripts.reviewer_bot_lib import deferred_gap_bookkeeping, reconcile, review_state
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reconcile_harness import review_dismissed_payload
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi


def test_execute_run_workflow_run_bookkeeping_only_reconcile_still_saves_state(tmp_path, monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Review Submitted Observer")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "bob"
    review["sidecars"]["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload_kind": "deferred_review_submitted",
                "schema_version": 3,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 700,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:11",
                "pr_number": 42,
                "review_id": 11,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_ID="700",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []
    synced_issue_numbers = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    def fake_workflow_run_result(bot, current):
        harness.runtime.collect_touched_item(42)
        deferred_gap_bookkeeping.mark_reconciled_source_event(
            current["active_reviews"]["42"],
            "pull_request_review:11",
            reconciled_at="2026-01-01T00:00:00+00:00",
        )
        deferred_gap_bookkeeping.clear_deferred_gap(current["active_reviews"]["42"], "pull_request_review:11")
        return reconcile.WorkflowRunHandlerResult(True, [42])

    monkeypatch.setattr(reconcile, "handle_workflow_run_event_result", fake_workflow_run_result)
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["sidecars"]["reconciled_source_events"]),
                "gap_present": "pull_request_review:11" in current["active_reviews"]["42"]["sidecars"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["pull_request_review:11"], "gap_present": False}]
    assert synced_issue_numbers == [42]

def test_execute_run_workflow_run_deferred_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Comment Router")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload_kind": "deferred_comment",
                "schema_version": 3,
                "source_workflow_name": "Reviewer Bot PR Comment Router",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
                "source_run_id": 710,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:210",
                "pr_number": 42,
                "comment_id": 210,
                "comment_body": "@guidelines-bot /queue",
                "comment_created_at": "2026-03-17T10:00:00Z",
                "comment_author": "bob",
                "comment_author_id": 7,
                "comment_user_type": "User",
                "comment_sender_type": "User",
                "comment_installation_id": None,
                "comment_performed_via_github_app": False,
                "issue_author": "dana",
                "issue_state": "open",
                "issue_labels": ["coding guideline"],
            }
        ),
        encoding="utf-8",
    )
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_ID="710",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    def fake_comment_workflow_run_result(bot, current):
        harness.runtime.collect_touched_item(42)
        deferred_gap_bookkeeping.mark_reconciled_source_event(
            current["active_reviews"]["42"],
            "issue_comment:210",
            reconciled_at="2026-01-01T00:00:00+00:00",
        )
        deferred_gap_bookkeeping.clear_deferred_gap(current["active_reviews"]["42"], "issue_comment:210")
        return reconcile.WorkflowRunHandlerResult(True, [42])

    monkeypatch.setattr(reconcile, "handle_workflow_run_event_result", fake_comment_workflow_run_result)
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["sidecars"]["reconciled_source_events"]),
                "gap_present": "issue_comment:210" in current["active_reviews"]["42"]["sidecars"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["issue_comment:210"], "gap_present": False}]

def test_execute_run_workflow_run_deferred_review_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Review Comment Observer")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["sidecars"]["deferred_gaps"]["pull_request_review_comment:310"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload_kind": "deferred_review_comment",
                "schema_version": 3,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 711,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:310",
                "pr_number": 42,
                "comment_id": 310,
                "comment_body": "plain text review comment",
                "comment_created_at": "2026-03-17T10:00:00Z",
                "comment_author": "alice",
                "comment_author_id": 11,
                "comment_user_type": "User",
                "comment_sender_type": "User",
                "comment_installation_id": None,
                "comment_performed_via_github_app": False,
                "issue_author": "dana",
                "issue_state": "open",
                "issue_labels": ["coding guideline"],
            }
        ),
        encoding="utf-8",
    )
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_ID="711",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))

    def fake_review_comment_workflow_run_result(bot, current):
        harness.runtime.collect_touched_item(42)
        deferred_gap_bookkeeping.mark_reconciled_source_event(
            current["active_reviews"]["42"],
            "pull_request_review_comment:310",
            reconciled_at="2026-01-01T00:00:00+00:00",
        )
        deferred_gap_bookkeeping.clear_deferred_gap(
            current["active_reviews"]["42"],
            "pull_request_review_comment:310",
        )
        return reconcile.WorkflowRunHandlerResult(True, [42])

    monkeypatch.setattr(reconcile, "handle_workflow_run_event_result", fake_review_comment_workflow_run_result)
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["sidecars"]["reconciled_source_events"]),
                "gap_present": "pull_request_review_comment:310"
                in current["active_reviews"]["42"]["sidecars"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_snapshots == [
        {"reconciled": ["pull_request_review_comment:310"], "gap_present": False}
    ]


def test_execute_run_workflow_run_missing_row_records_orphan_then_projects(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Review Dismissed Observer")
    payload = review_dismissed_payload(
        pr_number=42,
        review_id=12,
        source_event_key="pull_request_review_dismissed:12",
        source_dismissed_at=None,
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=712,
        source_run_attempt=1,
    )
    payload_path = tmp_path / "deferred-review-dismissed.json"
    payload_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    harness.runtime.stub_deferred_payload(payload)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_ID="712",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
    )
    state = make_state()
    save_snapshots = []
    projected_issue_numbers = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_save_state(lambda current: save_snapshots.append(current) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: projected_issue_numbers.extend(issue_numbers) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert state["active_reviews"] == {}
    assert state["sidecars"]["orphaned_deferred_reconcile_events"]["pull_request_review_dismissed:12"]["recovery_status"] == "blocked_live_pr_unavailable"
    assert save_snapshots
    assert projected_issue_numbers == [42]


def test_execute_run_workflow_run_closed_live_pr_safe_noop_does_not_save_or_project(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Review Dismissed Observer")
    payload = review_dismissed_payload(
        pr_number=42,
        review_id=12,
        source_event_key="pull_request_review_dismissed:12",
        source_dismissed_at="2026-03-17T10:10:00Z",
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=712,
        source_run_attempt=1,
    )
    payload_path = tmp_path / "deferred-review-dismissed.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    harness.runtime.stub_deferred_payload(payload)
    harness.runtime.github.stub(
        RouteGitHubApi().add_request(
            "GET",
            "pulls/42",
            status_code=200,
            payload={"state": "closed", "head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []},
        )
    )
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_ID="712",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
    )
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["pull_request_review_dismissed:12"] = {"reason": "artifact_missing"}
    save_snapshots = []
    projected_issue_numbers = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_save_state(lambda current: save_snapshots.append(current) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: projected_issue_numbers.extend(issue_numbers) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is False
    assert review["review_dismissal"]["accepted"] is None
    assert review["sidecars"]["deferred_gaps"] == {"pull_request_review_dismissed:12": {"reason": "artifact_missing"}}
    assert review["sidecars"]["reconciled_source_events"] == {}
    assert save_snapshots == []
    assert projected_issue_numbers == []


def test_m1_reconcile_exposes_typed_workflow_run_result_shape():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")

    assert "class WorkflowRunHandlerResult:" in reconcile_text
    for field in ["state_changed", "touched_items"]:
        assert field in reconcile_text
