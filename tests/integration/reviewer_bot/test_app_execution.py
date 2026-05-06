import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import (
    event_inputs,
    maintenance,
    maintenance_schedule,
    reconcile,
    review_state,
    state_store,
)
from scripts.reviewer_bot_lib.config import STATUS_AWAITING_REVIEWER_RESPONSE_LABEL
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.http_responses import FakeGitHubResponse
from tests.fixtures.reviewer_bot import make_state, make_tracked_review_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result

pytestmark = pytest.mark.integration


def _configure_bootstrapped_runtime_with_real_status_projection(monkeypatch, state, *, issue_state: str):
    runtime = reviewer_bot._runtime_bot()
    label_ops = []

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if method == "POST" and endpoint == "labels":
            return runtime.GitHubApiResult(201, {}, {}, "created", True, None, 0, None)
        if method == "DELETE" and endpoint.startswith("issues/42/labels/"):
            label_ops.append(("remove", unquote(endpoint.rsplit("/", 1)[-1])))
            return runtime.GitHubApiResult(204, None, {}, "", True, None, 0, None)
        if method == "POST" and endpoint == "issues/42/labels":
            label_ops.append(("add", data["labels"][0]))
            return runtime.GitHubApiResult(200, {}, {}, "ok", True, None, 0, None)
        raise AssertionError((method, endpoint, data))

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(
        runtime.github,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {
            "number": issue_number,
            "state": issue_state,
            "labels": [{"name": STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}],
            "pull_request": {},
        },
    )
    monkeypatch.setattr(runtime, "github_api_request", github_api_request)
    return runtime, label_ops


def _route_bootstrapped_rest_request(routes: RouteGitHubApi):
    def request(method, url, *, headers=None, json_data=None, timeout_seconds=None):
        parts = urlparse(url).path.strip("/").split("/")
        endpoint = "/".join(parts[3:])
        result = routes.github_api_request(
            method,
            endpoint,
            data=json_data,
            extra_headers=headers,
            timeout_seconds=timeout_seconds,
        )
        return FakeGitHubResponse(
            result.status_code or 0,
            payload=result.payload,
            text=result.text,
            headers=result.headers,
        )

    return request


def test_app_harness_exposes_focused_runtime_services(monkeypatch):
    harness = AppHarness(monkeypatch)

    assert harness.state_store is harness.runtime.state_store
    assert harness.locks is harness.runtime.locks
    assert harness.handlers is harness.runtime.handlers
    assert harness.touch_tracker is harness.runtime.touch_tracker


def test_execute_run_reloads_state_before_syncing_status_labels(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")

    initial_state = make_state()
    reloaded_state = make_state()
    load_calls = {"count": 0}
    save_completed = {"value": False}
    sync_inputs = {}
    release_calls = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            return initial_state
        return reloaded_state

    def fake_handle_comment_event(state):
        assert state is initial_state
        harness.runtime.collect_touched_item(42)
        return True

    def fake_save_state(state):
        assert state is initial_state
        save_completed["value"] = True
        return True

    def fake_sync_status_labels_for_items(state, issue_numbers):
        sync_inputs["save_completed"] = save_completed["value"]
        sync_inputs["state"] = state
        sync_inputs["issue_numbers"] = list(issue_numbers)
        assert state is reloaded_state
        assert list(issue_numbers) == [42]
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: release_calls.append("released") or True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", fake_handle_comment_event)
    harness.stub_save_state(fake_save_state)
    harness.stub_sync_status_labels(fake_sync_status_labels_for_items)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert load_calls["count"] >= 2
    assert sync_inputs == {
        "save_completed": True,
        "state": reloaded_state,
        "issue_numbers": [42],
    }
    assert release_calls == ["released"]


def test_execute_run_deferred_pr_issue_comment_does_not_call_direct_handler(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="issue_comment",
        EVENT_ACTION="created",
        IS_PULL_REQUEST="true",
        REVIEWER_BOT_ROUTE_OUTCOME="deferred_reconcile",
    )
    handler_calls = []
    lock_calls = []
    harness.stub_lock(
        acquire=lambda: lock_calls.append("acquired"),
        release=lambda: lock_calls.append("released") or True,
    )
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_handler("handle_comment_event", lambda state: handler_calls.append(state) or True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is False
    assert lock_calls == []
    assert handler_calls == []


def test_execute_run_successful_router_without_artifact_stays_read_only(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Comment Router")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )
    calls = []
    harness.runtime.load_deferred_payload = lambda: (_ for _ in ()).throw(RuntimeError("missing artifact"))
    harness.stub_lock(acquire=lambda: calls.append("lock_acquire"), release=lambda: calls.append("lock_release") or True)
    harness.stub_pass_until(lambda state: calls.append("pass_until") or (state, []))
    harness.stub_sync_members(lambda state: calls.append("sync_members") or (state, []))
    monkeypatch.setattr(
        reconcile,
        "handle_workflow_run_event_result",
        lambda bot, state: pytest.fail("missing router artifact must skip reconcile before mutating phases"),
    )

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is False
    assert calls == []
    assert harness.state_store.save_calls == []


def test_execute_run_non_success_workflow_run_reconcile_stays_read_only_and_non_closing(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Review Submitted Observer")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="failure",
    )
    state = make_state(epoch="freshness_v15")
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}
    calls = []
    harness.stub_lock(acquire=lambda: calls.append("lock_acquire"), release=lambda: calls.append("lock_release") or True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: calls.append("pass_until") or (current, []))
    harness.stub_sync_members(lambda current: calls.append("sync_members") or (current, []))
    def fake_reconcile(bot, current):
        calls.append("reconcile_diagnostic")
        return reconcile.WorkflowRunHandlerResult(state_changed=False, touched_items=[])

    monkeypatch.setattr(reconcile, "handle_workflow_run_event_result", fake_reconcile)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is False
    assert calls == ["lock_acquire", "pass_until", "sync_members", "reconcile_diagnostic", "lock_release"]
    assert harness.state_store.save_calls == []
    assert review["sidecars"]["deferred_gaps"] == {"pull_request_review:11": {"reason": "artifact_missing"}}
    assert review["sidecars"]["reconciled_source_events"] == {}


def test_execute_run_malformed_optional_router_artifact_fails_in_app_path(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_workflow_run_name("Reviewer Bot PR Comment Router")
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )
    calls = []
    harness.runtime.load_deferred_payload = lambda: (_ for _ in ()).throw(RuntimeError("invalid deferred context"))
    harness.stub_lock(acquire=lambda: calls.append("lock_acquire"), release=lambda: calls.append("lock_release") or True)
    harness.stub_pass_until(lambda state: calls.append("pass_until") or (state, []))
    harness.stub_sync_members(lambda state: calls.append("sync_members") or (state, []))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is False
    assert calls == []
    assert harness.state_store.load_calls == []
    assert harness.state_store.save_calls == []


def test_execute_run_opened_issue_assignment_failure_does_not_persist_reviewer_state(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    saved = []

    monkeypatch.setattr(runtime.locks, "acquire", lambda: setattr(runtime, "ACTIVE_LEASE_CONTEXT", object()) or runtime.ACTIVE_LEASE_CONTEXT)
    monkeypatch.setattr(runtime.locks, "release", lambda: setattr(runtime, "ACTIVE_LEASE_CONTEXT", None) or True)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: saved.append(current_state.copy()) or True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.github, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(
        runtime.github,
        "get_issue_assignees_result",
        lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(200, [], {}, "ok", True, None, 0, None),
    )
    monkeypatch.setattr(runtime.adapters.queue, "get_next_reviewer", lambda current_state, skip_usernames=None: "alice")
    monkeypatch.setattr(
        runtime.github,
        "assign_issue_assignee",
        lambda issue_number, username: runtime.AssignmentAttempt(
            success=False,
            status_code=502,
            exhausted_retryable_failure=True,
            failure_kind="server_error",
        ),
    )
    monkeypatch.setattr(runtime.github, "post_comment", lambda issue_number, body: True)
    monkeypatch.setenv("EVENT_NAME", "issues")
    monkeypatch.setenv("EVENT_ACTION", "opened")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')
    monkeypatch.setenv("ISSUE_STATE", "open")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_CREATED_AT", "2026-03-17T10:00:00Z")

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert saved
    saved_review = saved[-1]["active_reviews"]["42"]
    assert saved_review["current_reviewer"] is None
    assert saved_review["sidecars"]["repair_markers"]["assignment_confirm_read"]["reason"] == "final_assignee_mismatch"


def test_execute_run_opened_issue_adopts_existing_single_live_assignee(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    saved = []

    monkeypatch.setattr(runtime.locks, "acquire", lambda: setattr(runtime, "ACTIVE_LEASE_CONTEXT", object()) or runtime.ACTIVE_LEASE_CONTEXT)
    monkeypatch.setattr(runtime.locks, "release", lambda: setattr(runtime, "ACTIVE_LEASE_CONTEXT", None) or True)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: saved.append(current_state.copy()) or True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.github, "get_issue_assignees", lambda issue_number: ["alice"])
    monkeypatch.setattr(
        runtime.github,
        "get_issue_assignees_result",
        lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(200, ["alice"], {}, "ok", True, None, 0, None),
    )
    monkeypatch.setenv("EVENT_NAME", "issues")
    monkeypatch.setenv("EVENT_ACTION", "opened")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')
    monkeypatch.setenv("ISSUE_STATE", "open")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_CREATED_AT", "2026-03-17T10:00:00Z")

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert saved[-1]["active_reviews"]["42"]["current_reviewer"] == "alice"
    receipt = next(iter(saved[-1]["state_issue_write_receipts"].values()))
    assert receipt["write_status"] == "persisted"
    assert receipt["state_save_succeeded"] is True

def test_execute_run_returns_failure_when_save_state_fails(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    harness.stub_save_state(lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is True
    receipt_logs = [record for record in harness.runtime.logger.records if record["message"] == "state issue write receipt"]
    assert receipt_logs[-1]["fields"]["write_status"] == "failed_after_external_side_effect"
    assert receipt_logs[-1]["fields"]["next_recovery_action"] == "recover_from_live_github_receipt"


def test_execute_run_persists_recovery_receipt_after_initial_save_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    save_results = iter([False, True])
    harness.stub_save_state(lambda state: next(save_results))

    result = harness.run_execute()

    assert result.exit_code == 1
    assert len(harness.state_store.save_calls) == 2
    receipts = harness.state_store.save_calls[-1]["state_issue_write_receipts"]
    assert any(
        receipt["write_status"] == "failed_after_external_side_effect"
        and receipt["next_recovery_action"] == "recover_from_live_github_receipt"
        for receipt in receipts.values()
    )


def test_execute_run_releases_lock_after_save_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    release_calls = []
    harness.stub_lock(acquire=lambda: None, release=lambda: release_calls.append("released") or True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: True)
    harness.stub_save_state(lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert release_calls == ["released"]


def test_execute_run_persists_projection_repair_marker_after_projection_failure(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    initial_state = make_state()
    reloaded_state = make_state()
    make_tracked_review_state(reloaded_state, 42, reviewer="alice")
    load_count = {"value": 0}
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        load_count["value"] += 1
        if load_count["value"] == 1:
            return initial_state
        return reloaded_state

    def fake_handle_comment_event(state):
        harness.runtime.collect_touched_item(42)
        return True

    def fake_save_state(state):
        saved_states.append(state.copy())
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(fake_load_state)
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", fake_handle_comment_event)
    harness.stub_save_state(fake_save_state)
    harness.stub_sync_status_labels(lambda state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is True
    assert len(saved_states) == 2
    assert saved_states[-1]["active_reviews"]["42"]["sidecars"]["repair_markers"]["status_label_projection"]["kind"] == "projection_failure"


def test_execute_run_manual_read_only_policy_blocks_touched_status_label_sync(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_dispatch",
        EVENT_ACTION="",
        MANUAL_ACTION="preview-status-label-projection",
        ISSUE_NUMBER=42,
        VALIDATION_NONCE="nonce",
    )
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())

    def fake_manual_dispatch(state):
        harness.runtime.collect_touched_item(42)
        return False

    harness.stub_handler("handle_manual_dispatch", fake_manual_dispatch)
    harness.stub_sync_status_labels(lambda current, issue_numbers: pytest.fail("read-only manual policy must not sync labels"))

    result = harness.run_execute()

    assert result.exit_code == 0
    assert result.state_changed is False


def test_execute_run_returns_failure_when_lock_release_fails(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="issue_comment", EVENT_ACTION="created")
    harness.stub_lock(acquire=lambda: None, release=lambda: False)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    harness.stub_handler("handle_comment_event", lambda state: False)

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.release_failed is True

def test_execute_run_returns_failure_for_invalid_workflow_run_context(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        REVIEWER_BOT_WORKFLOW_KIND="reconcile",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )
    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: make_state())
    harness.stub_pass_until(lambda state: (state, []))
    harness.stub_sync_members(lambda state: (state, []))
    monkeypatch.setattr(
        reconcile,
        "handle_workflow_run_event_result",
        lambda bot, state: (_ for _ in ()).throw(RuntimeError("invalid deferred context")),
    )

    result = harness.run_execute()

    assert result.exit_code == 1
    assert result.state_changed is False


def test_bootstrapped_runtime_executes_direct_issue_comment_path_with_strict_request_inputs(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    seen = {}

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def handle_comment_event(current_state):
        assert current_state is state
        seen["request"] = event_inputs.build_comment_event_request(runtime)
        runtime.collect_touched_item(42)
        return True

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.handlers, "handle_comment_event", handle_comment_event)
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "open")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["triage"]')
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ID", "200")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-04-13T04:30:00Z")
    monkeypatch.delenv("COMMENT_SOURCE_EVENT_KEY", raising=False)
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_SENDER_TYPE", "User")
    monkeypatch.delenv("COMMENT_INSTALLATION_ID", raising=False)
    monkeypatch.setenv("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert seen["request"].is_pull_request is False
    assert seen["request"].comment_author_id == 200
    assert seen["request"].comment_source_event_key == "issue_comment:100"
    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_bootstrapped_runtime_executes_pr_metadata_closed_dispatch_path(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    calls = []

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def handle_closed_event(current_state):
        calls.append(current_state)
        return True

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.handlers, "handle_closed_event", handle_closed_event)
    monkeypatch.setenv("EVENT_NAME", "pull_request_target")
    monkeypatch.setenv("EVENT_ACTION", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["triage"]')
    monkeypatch.setenv("PR_HEAD_SHA", "head-1")
    monkeypatch.setenv("PR_CLOSED_AT", "2026-04-13T04:31:00Z")

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert context.event_name == "pull_request_target"
    assert context.event_action == "closed"
    assert calls == [state]
    assert result.exit_code == 0
    assert result.state_changed is True
    assert runtime.ACTIVE_LEASE_CONTEXT is None


@pytest.mark.parametrize(
    ("event_action", "handler_name", "label_name"),
    [
        ("opened", "handle_issue_or_pr_opened", ""),
        ("labeled", "handle_labeled_event", "coding guideline"),
        ("unlabeled", "handle_unlabeled_event", "coding guideline"),
        ("reopened", "handle_reopened_event", ""),
        ("closed", "handle_closed_event", ""),
        ("synchronize", "handle_pull_request_target_synchronize", ""),
    ],
)
def test_bootstrapped_runtime_executes_pr_metadata_dispatch_matrix(
    monkeypatch, event_action, handler_name, label_name
):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    calls = []

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def handler(current_state):
        calls.append(current_state)
        return True

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.handlers, handler_name, handler)
    monkeypatch.setenv("EVENT_NAME", "pull_request_target")
    monkeypatch.setenv("EVENT_ACTION", event_action)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')
    monkeypatch.setenv("LABEL_NAME", label_name)
    monkeypatch.setenv("PR_HEAD_SHA", "head-1")
    monkeypatch.setenv("PR_CREATED_AT", "2026-04-13T04:30:00Z")
    monkeypatch.setenv("PR_UPDATED_AT", "2026-04-13T04:31:00Z")
    monkeypatch.setenv("PR_CLOSED_AT", "2026-04-13T04:32:00Z")

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert context.event_name == "pull_request_target"
    assert context.event_action == event_action
    assert calls == [state]
    assert result.exit_code == 0
    assert result.state_changed is True
    assert runtime.ACTIVE_LEASE_CONTEXT is None


@pytest.mark.parametrize(
    ("event_action", "handler_name", "issue_state", "label_name"),
    [
        ("opened", "handle_issue_or_pr_opened", "open", ""),
        ("assigned", "handle_assigned_event", "open", ""),
        ("unassigned", "handle_unassigned_event", "open", ""),
        ("labeled", "handle_labeled_event", "open", "coding guideline"),
        ("unlabeled", "handle_unlabeled_event", "open", "coding guideline"),
        ("edited", "handle_issue_edited_event", "open", ""),
        ("reopened", "handle_reopened_event", "open", ""),
        ("closed", "handle_closed_event", "closed", ""),
    ],
)
def test_bootstrapped_runtime_executes_issue_lifecycle_dispatch_matrix(
    monkeypatch, event_action, handler_name, issue_state, label_name
):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    calls = []

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def handler(current_state):
        calls.append(current_state)
        return True

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: state)
    monkeypatch.setattr(runtime.state_store, "save_state", lambda current_state: True)
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_status_labels_for_items", lambda current_state, issue_numbers: False)
    monkeypatch.setattr(runtime.handlers, handler_name, handler)
    monkeypatch.setenv("EVENT_NAME", "issues")
    monkeypatch.setenv("EVENT_ACTION", event_action)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", issue_state)
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')
    monkeypatch.setenv("LABEL_NAME", label_name)
    monkeypatch.setenv("ISSUE_CREATED_AT", "2026-04-13T04:30:00Z")
    monkeypatch.setenv("ISSUE_UPDATED_AT", "2026-04-13T04:31:00Z")
    monkeypatch.setenv("ISSUE_CLOSED_AT", "2026-04-13T04:32:00Z")

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert context.event_name == "issues"
    assert context.event_action == event_action
    assert calls == [state]
    assert result.exit_code == 0
    assert result.state_changed is True
    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_bootstrapped_runtime_pr_metadata_closed_executes_real_status_label_projection_path(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    assert review is not None
    runtime, label_ops = _configure_bootstrapped_runtime_with_real_status_projection(
        monkeypatch, state, issue_state="closed"
    )
    monkeypatch.setenv("EVENT_NAME", "pull_request_target")
    monkeypatch.setenv("EVENT_ACTION", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("ISSUE_LABELS", '["triage"]')
    monkeypatch.setenv("PR_HEAD_SHA", "head-1")
    monkeypatch.setenv("PR_CLOSED_AT", "2026-04-13T04:31:00Z")

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert label_ops == [("remove", STATUS_AWAITING_REVIEWER_RESPONSE_LABEL)]
    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_bootstrapped_runtime_workflow_dispatch_repair_status_labels_uses_real_projection_path(monkeypatch, tmp_path):
    state = make_state()
    runtime, label_ops = _configure_bootstrapped_runtime_with_real_status_projection(
        monkeypatch, state, issue_state="open"
    )
    monkeypatch.setattr(maintenance.reviews, "list_open_items_with_status_labels", lambda bot: [42])
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "repair-review-status-labels")
    monkeypatch.setenv("VALIDATION_NONCE", "repair-nonce")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_RUN_ID", "9001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "workflow-head")
    monkeypatch.setenv("REPAIR_SUMMARY_PATH", str(tmp_path / "repair-summary.json"))

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is False
    assert label_ops == [("remove", STATUS_AWAITING_REVIEWER_RESPONSE_LABEL)]
    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_bootstrapped_runtime_workflow_dispatch_check_overdue_preserves_touched_item_projection(monkeypatch):
    state = make_state()
    runtime, label_ops = _configure_bootstrapped_runtime_with_real_status_projection(
        monkeypatch, state, issue_state="open"
    )
    monkeypatch.setattr(
        maintenance_schedule,
        "handle_scheduled_check_result",
        lambda bot, current: maintenance.ScheduleHandlerResult(False, [42]),
    )
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "check-overdue")

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert label_ops == [("remove", STATUS_AWAITING_REVIEWER_RESPONSE_LABEL)]
    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_bootstrapped_runtime_workflow_dispatch_check_overdue_uses_real_save_state_without_conditional_issue_headers(
    monkeypatch,
):
    runtime = reviewer_bot._runtime_bot()
    state = make_state()
    state["status_projection_epoch"] = runtime.STATUS_PROJECTION_EPOCH
    issue_number = "314"
    issue_body = state_store.render_state_issue_body(state)
    routes = RouteGitHubApi().add_request_sequence(
        "GET",
        f"issues/{issue_number}",
        [
            github_result(
                200,
                {"body": issue_body, "html_url": f"https://example.com/issues/{issue_number}"},
                headers={"ETag": '"etag-1"'},
            ),
            github_result(
                200,
                {"body": issue_body, "html_url": f"https://example.com/issues/{issue_number}"},
                headers={"ETag": '"etag-2"'},
            ),
        ],
    ).add_request(
        "PATCH",
        f"issues/{issue_number}",
        status_code=200,
        payload={"body": "updated"},
    )

    def acquire_lock():
        runtime.ACTIVE_LEASE_CONTEXT = object()
        return runtime.ACTIVE_LEASE_CONTEXT

    def release_lock():
        runtime.ACTIVE_LEASE_CONTEXT = None
        return True

    def handle_scheduled_check_result(bot, current_state):
        del bot
        current_state["current_index"] = 1
        return maintenance.ScheduleHandlerResult(True, [])

    monkeypatch.setattr(runtime.locks, "acquire", acquire_lock)
    monkeypatch.setattr(runtime.locks, "release", release_lock)
    monkeypatch.setattr(runtime.locks, "refresh", lambda: True)
    monkeypatch.setattr(runtime.rest_transport, "request", _route_bootstrapped_rest_request(routes))
    monkeypatch.setattr(runtime.adapters.workflow, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(runtime.adapters.workflow, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(maintenance_schedule, "handle_scheduled_check_result", handle_scheduled_check_result)
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("EVENT_ACTION", "")
    monkeypatch.setenv("MANUAL_ACTION", "check-overdue")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("STATE_ISSUE_NUMBER", issue_number)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0
    assert result.state_changed is True
    assert runtime.ACTIVE_LEASE_CONTEXT is None
    assert sum(
        1
        for call in routes.request_calls
        if call.method == "GET" and call.endpoint == f"issues/{issue_number}"
    ) >= 2
    patch_call = routes.request_calls[-1]
    assert patch_call.method == "PATCH"
    assert patch_call.endpoint == f"issues/{issue_number}"
    assert patch_call.data is not None
    assert "current_index: 1" in patch_call.data["body"]
    assert patch_call.extra_headers is not None
    assert all(header_name.lower() != "if-match" for header_name in patch_call.extra_headers)


def test_d4a_app_branch_to_phase_map_is_frozen_pre_edit():
    app_text = Path("scripts/reviewer_bot_lib/app.py").read_text(encoding="utf-8")

    assert "if lock_required:" in app_text
    assert "state = bot.state_store.load_state(fail_on_unavailable=lock_required)" in app_text
    assert "state, restored = bot.adapters.workflow.process_pass_until_expirations(state)" in app_text
    assert "state, sync_changes = bot.adapters.workflow.sync_members_with_queue(state)" in app_text
    assert "if workflow_run_result is not None:" in app_text
    assert "touched_items = workflow_run_result.touched_items" in app_text
    assert "elif schedule_result is not None:" in app_text
    assert "touched_items = schedule_result.touched_items" in app_text
    assert "touched_items = bot.drain_touched_items()" in app_text
    assert '_revalidate_epoch(bot, loaded_epoch, "authoritative save")' in app_text
    assert "if not bot.state_store.save_state(state):" in app_text
    assert "state = bot.state_store.load_state(fail_on_unavailable=True)" in app_text
    assert '_revalidate_epoch(bot, loaded_epoch, "status-label projection")' in app_text
    assert "if _mark_projection_repair_needed(bot, state, touched_items, str(exc)):" in app_text
    assert "if not bot.locks.release():" in app_text


def test_d4b_post_edit_phase_map_matches_pre_edit_transaction_shape():
    pre_map = json.loads(Path("tests/fixtures/equivalence/app/transaction_phase_map.json").read_text(encoding="utf-8"))
    post_map = json.loads(Path("tests/fixtures/equivalence/app/post_edit_transaction_phase_map.json").read_text(encoding="utf-8"))

    assert post_map["harness_id"] == "D4b app post-edit transaction phase map"
    assert post_map["branch_to_phase"] == pre_map["branch_to_phase"]


def test_m1_app_consumes_typed_workflow_run_result_instead_of_boolean_only_signal():
    app_text = Path("scripts/reviewer_bot_lib/app.py").read_text(encoding="utf-8")

    assert "workflow_run_result: reconcile.WorkflowRunHandlerResult | None = None" in app_text
    assert "workflow_run_result = reconcile.handle_workflow_run_event_result(bot, state)" in app_text
    assert "state_changed = workflow_run_result.state_changed" in app_text
    assert "if workflow_run_result is not None:" in app_text
    assert "touched_items = workflow_run_result.touched_items" in app_text
    assert "elif schedule_result is not None:" in app_text
    assert "touched_items = schedule_result.touched_items" in app_text
