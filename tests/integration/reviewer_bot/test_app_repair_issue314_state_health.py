import json

import pytest

from scripts.reviewer_bot_lib import app
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state, make_tracked_review_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_execute_run_repair_issue314_state_health_removes_closed_rows_through_state_store(
    monkeypatch,
    tmp_path,
):
    harness = AppHarness(monkeypatch)
    summary_path = tmp_path / "repair" / "issue314-state-health-repair-summary.json"
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="repair-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-repair",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1001",
        GITHUB_RUN_ATTEMPT="5",
        STATE_ISSUE_NUMBER=314,
    )
    harness.stub_lock()
    monkeypatch.setenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", str(summary_path))

    state = make_state()
    state["status_projection_epoch"] = "stale_projection_epoch"
    make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/42",
        status_code=200,
        payload={
            "number": 42,
            "state": "closed",
            "pull_request": {},
            "labels": [{"name": "status: awaiting reviewer response"}],
        },
    ).add_request(
        "GET",
        "issues/42/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    )
    harness.runtime.github.stub(routes)
    saved = []
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_save_state(lambda current: saved.append(json.loads(json.dumps(current))) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("issue314 repair should not broad-sync labels")))
    monkeypatch.setattr(
        app,
        "collect_status_projection_repair_items",
        lambda bot, state: (_ for _ in ()).throw(AssertionError("issue314 repair broadened through epoch repair")),
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["repair_action"] == "repair-issue314-state-health"
    assert payload["state_issue_number"] == 314
    assert payload["issue_number"] == 314
    assert payload["target_collection_mode"] == "global_issue314_state_health"
    assert payload["active_rows_inspected"] == [42]
    assert payload["rows_removed_closed"] == [42]
    assert payload["reviewer_facing_reminder_posts_attempted"] == 0
    assert payload["manual_issue314_edit_status"] == "not_attempted"
    assert payload["artifact_name"] == "reviewer-bot-repair-output-1001-attempt-5"
    assert payload["artifact_file"] == "issue314-state-health-repair-summary.json"
    assert payload["output_keys"] == sorted(payload.keys())
    assert saved
    assert "42" not in saved[-1]["active_reviews"]
    assert saved[-1]["status_projection_epoch"] == "stale_projection_epoch"


def test_execute_run_repair_issue314_state_health_emits_summary_only_after_state_save(
    monkeypatch,
    tmp_path,
):
    harness = AppHarness(monkeypatch)
    summary_path = tmp_path / "repair" / "issue314-state-health-repair-summary.json"
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="repair-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-repair",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1002",
        GITHUB_RUN_ATTEMPT="1",
        STATE_ISSUE_NUMBER=314,
    )
    harness.stub_lock()
    monkeypatch.setenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", str(summary_path))

    state = make_state()
    make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/42",
        status_code=200,
        payload={"number": 42, "state": "closed", "pull_request": {}, "labels": []},
    ).add_request(
        "GET",
        "issues/42/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    )
    harness.runtime.github.stub(routes)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_save_state(lambda current: False)
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("issue314 repair should not broad-sync labels")))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert not summary_path.exists()


def test_execute_run_repair_issue314_state_health_requires_identity(monkeypatch, tmp_path):
    harness = AppHarness(monkeypatch)
    summary_path = tmp_path / "repair" / "issue314-state-health-repair-summary.json"
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="repair-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1003",
        GITHUB_RUN_ATTEMPT="1",
        STATE_ISSUE_NUMBER=314,
    )
    harness.stub_lock()
    monkeypatch.setenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", str(summary_path))
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("identity-blocked repair should not save state")))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert not summary_path.exists()


def test_execute_run_repair_issue314_state_health_repairs_awaiting_reviewer_label_drift(
    monkeypatch,
    tmp_path,
):
    harness = AppHarness(monkeypatch)
    summary_path = tmp_path / "repair" / "issue314-state-health-repair-summary.json"
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="repair-issue314-state-health",
        ISSUE_NUMBER=314,
        VALIDATION_NONCE="nonce-issue314-repair",
        GITHUB_SHA="workflow-head",
        GITHUB_REPOSITORY="rustfoundation/safety-critical-rust-coding-guidelines",
        GITHUB_RUN_ID="1004",
        GITHUB_RUN_ATTEMPT="1",
        STATE_ISSUE_NUMBER=314,
    )
    harness.stub_lock()
    monkeypatch.setenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", str(summary_path))

    state = make_state()
    make_tracked_review_state(
        state,
        360,
        reviewer="AlexCeleste",
        assigned_at="2026-01-01T00:00:00Z",
        active_cycle_started_at="2026-01-01T00:00:00Z",
    )
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/360",
        status_code=200,
        payload={
            "number": 360,
            "state": "open",
            "labels": [
                {"name": "status: awaiting reviewer response"},
                {"name": "status: draft"},
            ],
            "assignees": [{"login": "AlexCeleste"}],
        },
    ).add_request(
        "GET",
        "issues/360/comments?per_page=100&page=1",
        status_code=200,
        payload=[],
    ).add_request(
        "DELETE",
        "issues/360/labels/status%3A%20draft",
        status_code=204,
        payload=None,
    )
    harness.runtime.github.stub(routes)
    harness.runtime.github.post_comment_result = lambda issue_number, body: (_ for _ in ()).throw(
        AssertionError("issue314 repair should not post reviewer-facing reminders")
    )
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_save_state(lambda current: (_ for _ in ()).throw(AssertionError("label-only issue314 repair should not save state")))
    harness.stub_sync_status_labels(lambda current, issue_numbers: (_ for _ in ()).throw(AssertionError("issue314 repair should not broad-sync labels")))
    monkeypatch.setattr(
        app,
        "collect_status_projection_repair_items",
        lambda bot, state: (_ for _ in ()).throw(AssertionError("issue314 repair broadened through epoch repair")),
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["active_rows_inspected"] == [360]
    assert payload["rows_repaired"] == [360]
    assert payload["rows_blocked"] == []
    assert payload["status_labels_changed"] == [360]
    assert payload["reviewer_facing_reminder_posts_attempted"] == 0
    assert payload["result"] == "changed"
