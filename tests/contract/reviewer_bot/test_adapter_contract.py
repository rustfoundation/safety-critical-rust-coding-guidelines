import json
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import event_inputs, lease_lock, review_state
from scripts.reviewer_bot_lib.config import AssignmentAttempt, GitHubApiResult
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime, StdErrLogger
from scripts.reviewer_bot_lib.runtime_protocols import (
    CommentApplicationRuntimeContext,
    CommentRoutingRuntimeContext,
    ReconcileAdaptersContext,
    ReconcileRectifyGitHubContext,
    ReconcileRectifyRuntimeContext,
    ReconcileReviewStateAdapterContext,
    ReconcileWorkflowRuntimeContext,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.http_responses import FakeGitHubResponse
from tests.fixtures.reviewer_bot import make_state


def test_render_lock_commit_message_uses_direct_json_import():
    rendered = lease_lock.render_lock_commit_message(reviewer_bot._runtime_bot(), {"lock_state": "unlocked"})
    assert rendered.startswith("reviewer-bot-lock-v1\n")


def test_build_event_context_returns_structured_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("REVIEWER_BOT_WORKFLOW_KIND", "reconcile")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')
    event_path = Path("/tmp/test_build_event_context_returns_structured_context.json")
    event_path.write_text(json.dumps({"workflow_run": {"name": "Reviewer Bot PR Review Submitted Observer"}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    context = reviewer_bot.build_event_context()

    assert context.event_name == "workflow_run"
    assert context.workflow_kind == "reconcile"
    assert context.workflow_run_triggering_conclusion == "success"
    assert context.workflow_artifact_contract == "artifact_required"
    assert context.issue_labels == ("coding guideline",)


def test_execute_run_returns_execution_result(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    runtime = reviewer_bot._runtime_bot()
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: {"active_reviews": {}})

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context(runtime), runtime)

    assert result.exit_code == 0


def test_entrypoint_helpers_accept_explicit_runtime(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("EVENT_NAME", "issue_comment")
    runtime.set_config_value("EVENT_ACTION", "created")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "false")
    runtime.set_config_value("ISSUE_STATE", "open")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", "[]")
    runtime.set_config_value("COMMENT_ID", "100")
    runtime.set_config_value("COMMENT_AUTHOR", "alice")
    runtime.set_config_value("COMMENT_AUTHOR_ID", "200")
    runtime.set_config_value("COMMENT_BODY", "hello")
    runtime.set_config_value("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.set_config_value("COMMENT_SOURCE_EVENT_KEY", "issue_comment:100")
    runtime.set_config_value("COMMENT_USER_TYPE", "User")
    runtime.set_config_value("COMMENT_SENDER_TYPE", "User")
    runtime.set_config_value("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    runtime.handlers.stub("handle_comment_event", lambda state: False)

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert context.event_name == "issue_comment"
    assert result.exit_code == 0


def test_review_state_owner_exports_mutation_helper():
    hints = get_type_hints(review_state.ensure_review_entry)

    assert hints["return"] == dict | None


def test_runtime_head_repair_contract_is_runtime_scoped():
    hints = get_type_hints(ReconcileReviewStateAdapterContext.maybe_record_head_observation_repair)

    assert hints["return"].__name__ == "HeadObservationRepairResult"


def test_bootstrapped_runtime_re_exposes_retained_github_type_homes():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.AssignmentAttempt is AssignmentAttempt
    assert runtime.GitHubApiResult is GitHubApiResult


def test_bootstrapped_runtime_supports_typed_rest_and_assignment_paths(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    runtime.rest_transport = SimpleNamespace(
        request=lambda *args, **kwargs: FakeGitHubResponse(201, {"ok": True}, "ok")
    )

    response = runtime.github_api_request("GET", "issues/42")
    attempt = runtime.github.request_pr_reviewer_assignment(42, "alice")

    assert isinstance(response, GitHubApiResult)
    assert response.ok is True
    assert isinstance(attempt, AssignmentAttempt)
    assert attempt.success is True


def _protocol_member_names(protocol_type) -> set[str]:
    return set(protocol_type.__annotations__) | {
        name
        for name, value in protocol_type.__dict__.items()
        if not name.startswith("_") and callable(value)
    }


def test_k1b_context_freezes_exact_reconcile_workflow_runtime_seam():
    assert _protocol_member_names(ReconcileReviewStateAdapterContext) == {
        "maybe_record_head_observation_repair",
    }
    assert _protocol_member_names(ReconcileAdaptersContext) == {"review_state"}
    assert _protocol_member_names(ReconcileWorkflowRuntimeContext) == {
        "REVIEW_FRESHNESS_RUNBOOK_PATH",
        "logger",
        "clock",
        "adapters",
        "assert_lock_held",
        "load_deferred_payload",
        "get_config_value",
        "collect_touched_item",
        "drain_touched_items",
        "github_api_request",
        "github_api",
    }


def test_k1b_context_freezes_exact_reconcile_rectify_runtime_seam():
    assert _protocol_member_names(ReconcileRectifyGitHubContext) == {
        "get_pull_request_reviews",
        "get_user_permission_status",
    }
    assert _protocol_member_names(ReconcileRectifyRuntimeContext) == {
        "github",
        "adapters",
        "get_config_value",
        "parse_iso8601_timestamp",
        "github_api_request",
        "github_api",
        "satisfy_mandatory_approver_requirement",
    }


def test_k1d_rectify_context_refresh_keeps_live_pr_reads_in_runtime_seam_but_not_approval_owners():
    assert _protocol_member_names(ReconcileRectifyRuntimeContext) == {
        "github",
        "adapters",
        "get_config_value",
        "parse_iso8601_timestamp",
        "github_api_request",
        "github_api",
        "satisfy_mandatory_approver_requirement",
    }


def test_k1e_rectify_context_finalization_captures_retained_approval_support_without_broadening_workflow_seam():
    assert _protocol_member_names(ReconcileRectifyRuntimeContext) == {
        "github",
        "adapters",
        "get_config_value",
        "parse_iso8601_timestamp",
        "github_api_request",
        "github_api",
        "satisfy_mandatory_approver_requirement",
    }


def test_k1c_bootstrap_runtime_satisfies_frozen_workflow_reconcile_protocol():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReconcileWorkflowRuntimeContext)


def test_k1f_runtime_satisfies_finalized_rectify_runtime_protocol():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReconcileRectifyRuntimeContext)


def test_k2_runtime_satisfies_narrow_comment_runtime_protocols():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, CommentApplicationRuntimeContext)
    assert isinstance(runtime, CommentRoutingRuntimeContext)


def test_runtime_review_state_adapter_mutates_active_reviews():
    state = make_state()
    review = reviewer_bot._runtime_bot().adapters.review_state.ensure_review_entry(state, 42, create=True)

    assert review is state["active_reviews"]["42"]


def test_event_inputs_build_manual_dispatch_request_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("MANUAL_ACTION", "preview-reviewer-board")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")

    request = event_inputs.build_manual_dispatch_request(runtime)

    assert request.action == "preview-reviewer-board"
    assert request.issue_number == 42
    assert request.privileged_source_event_key == "issue_comment:100"


def test_event_inputs_build_comment_request_and_pr_admission_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("EVENT_NAME", "issue_comment")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_STATE", "open")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline"]')
    runtime.set_config_value("COMMENT_ID", "100")
    runtime.set_config_value("COMMENT_AUTHOR", "alice")
    runtime.set_config_value("COMMENT_AUTHOR_ID", "200")
    runtime.set_config_value("COMMENT_BODY", "hello")
    runtime.set_config_value("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.set_config_value("COMMENT_SOURCE_EVENT_KEY", "issue_comment:100")
    runtime.set_config_value("COMMENT_USER_TYPE", "User")
    runtime.set_config_value("COMMENT_SENDER_TYPE", "User")
    runtime.set_config_value("COMMENT_INSTALLATION_ID", "")
    runtime.set_config_value("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    runtime.set_config_value("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    runtime.set_config_value("PR_HEAD_FULL_NAME", "rustfoundation/safety-critical-rust-coding-guidelines")
    runtime.set_config_value("PR_AUTHOR", "dana")
    runtime.set_config_value("REVIEWER_BOT_ROUTE_OUTCOME", "trusted_direct")
    runtime.set_config_value("REVIEWER_BOT_TRUST_CLASS", "pr_trusted_direct")
    runtime.set_config_value("GITHUB_RUN_ID", "123")
    runtime.set_config_value("GITHUB_RUN_ATTEMPT", "2")

    request = event_inputs.build_comment_event_request(runtime)
    pr_admission = event_inputs.build_pr_comment_admission(runtime)

    assert request.issue_number == 42
    assert request.is_pull_request is True
    assert request.comment_id == 100
    assert request.comment_author == "alice"
    assert request.comment_author_id == 200
    assert request.issue_labels == ("coding guideline",)
    assert request.comment_source_event_key == "issue_comment:100"
    assert pr_admission is not None
    assert pr_admission.github_repository == "rustfoundation/safety-critical-rust-coding-guidelines"
    assert pr_admission.pr_head_full_name == "rustfoundation/safety-critical-rust-coding-guidelines"
    assert pr_admission.pr_author == "dana"
    assert pr_admission.issue_state == "open"
    assert pr_admission.issue_labels == ("coding guideline",)
    assert pr_admission.comment_author_id == 200
    assert pr_admission.github_run_id == 123
    assert pr_admission.github_run_attempt == 2


def test_event_inputs_build_pr_admission_rejects_request_boundary_mismatch(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("EVENT_NAME", "issue_comment")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_STATE", "open")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline"]')
    runtime.set_config_value("COMMENT_ID", "100")
    runtime.set_config_value("COMMENT_AUTHOR", "alice")
    runtime.set_config_value("COMMENT_AUTHOR_ID", "200")
    runtime.set_config_value("COMMENT_BODY", "hello")
    runtime.set_config_value("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.set_config_value("COMMENT_SOURCE_EVENT_KEY", "issue_comment:100")
    runtime.set_config_value("COMMENT_USER_TYPE", "User")
    runtime.set_config_value("COMMENT_SENDER_TYPE", "User")
    runtime.set_config_value("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    runtime.set_config_value("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    runtime.set_config_value("PR_HEAD_FULL_NAME", "rustfoundation/safety-critical-rust-coding-guidelines")
    runtime.set_config_value("PR_AUTHOR", "dana")
    runtime.set_config_value("REVIEWER_BOT_ROUTE_OUTCOME", "trusted_direct")
    runtime.set_config_value("REVIEWER_BOT_TRUST_CLASS", "pr_trusted_direct")
    runtime.set_config_value("GITHUB_RUN_ID", "123")
    runtime.set_config_value("GITHUB_RUN_ATTEMPT", "2")

    request = event_inputs.build_comment_event_request(runtime)
    mismatched = request.__class__(**{**request.__dict__, "comment_author_id": 201})

    with pytest.raises(event_inputs.InvalidEventInput, match="COMMENT_AUTHOR_ID must match"):
        event_inputs.build_pr_comment_admission(runtime, mismatched)


def test_event_inputs_build_assignment_and_privileged_requests_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_LABELS", '["fls-audit"]')
    runtime.set_config_value("REPO_OWNER", "rustfoundation")
    runtime.set_config_value("REPO_NAME", "safety-critical-rust-coding-guidelines")
    assignment_request = event_inputs.build_assignment_request(runtime, issue_number=42)
    privileged_request = event_inputs.build_privileged_command_request(
        runtime,
        issue_number=42,
        actor="alice",
        command_name="accept-no-fls-changes",
    )

    assert assignment_request.issue_number == 42
    assert assignment_request.issue_author == "dana"
    assert assignment_request.is_pull_request is True
    assert assignment_request.issue_labels == ("fls-audit",)
    assert assignment_request.repo_owner == "rustfoundation"
    assert assignment_request.repo_name == "safety-critical-rust-coding-guidelines"
    assert privileged_request.issue_number == 42
    assert privileged_request.actor == "alice"
    assert privileged_request.command_name == "accept-no-fls-changes"
    assert privileged_request.is_pull_request is True
    assert privileged_request.issue_labels == ("fls-audit",)


def test_github_api_assignment_helpers_use_runtime_config_for_pr_vs_issue(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    recorded = []

    def fake_request(method, endpoint, data=None, suppress_error_log=True, **kwargs):
        recorded.append((method, endpoint, data))
        return runtime.GitHubApiResult(201, {}, {}, "ok", True, None, 0, None)

    runtime.github_api_request = fake_request

    runtime.set_config_value("IS_PULL_REQUEST", "true")
    github_pr_attempt = reviewer_bot._runtime_bot(runtime).github.request_pr_reviewer_assignment(42, "alice")

    runtime.set_config_value("IS_PULL_REQUEST", "false")
    github_issue_attempt = reviewer_bot._runtime_bot(runtime).github.assign_issue_assignee(42, "alice")

    assert github_pr_attempt.success is True
    assert github_issue_attempt.success is True
    assert recorded == [
        ("POST", "pulls/42/requested_reviewers", {"reviewers": ["alice"]}),
        ("POST", "issues/42/assignees", {"assignees": ["alice"]}),
    ]


def test_event_inputs_parse_labels_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline", "fls-audit"]')

    assert event_inputs.parse_issue_labels(runtime) == ["coding guideline", "fls-audit"]


def test_event_inputs_build_issue_lifecycle_request_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline"]')
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("SENDER_LOGIN", "alice")
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    runtime.set_config_value("ISSUE_TITLE", "New title")
    runtime.set_config_value("ISSUE_BODY", "new body")
    runtime.set_config_value("ISSUE_CHANGES_TITLE_FROM", "Old title")
    runtime.set_config_value("ISSUE_CHANGES_BODY_FROM", "old body")
    runtime.set_config_value("PR_HEAD_SHA", "head-2")
    runtime.set_config_value("EVENT_CREATED_AT", "2026-03-17T10:05:00Z")

    request = event_inputs.build_issue_lifecycle_request(runtime)

    assert request.issue_number == 42
    assert request.is_pull_request is True
    assert request.issue_labels == ("coding guideline",)
    assert request.issue_author == "dana"
    assert request.sender_login == "alice"
    assert request.updated_at == "2026-03-17T10:00:00Z"
    assert request.issue_title == "New title"
    assert request.issue_body == "new body"
    assert request.previous_title == "Old title"
    assert request.previous_body == "old body"
    assert request.pr_head_sha == "head-2"
    assert request.event_created_at == "2026-03-17T10:05:00Z"


def test_event_inputs_build_label_and_sync_requests_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("LABEL_NAME", "sign-off: create pr")
    runtime.set_config_value("PR_HEAD_SHA", "head-2")
    runtime.set_config_value("EVENT_CREATED_AT", "2026-03-17T10:05:00Z")

    label_request = event_inputs.build_label_event_request(runtime)
    sync_request = event_inputs.build_pull_request_sync_request(runtime)

    assert label_request.issue_number == 42
    assert label_request.is_pull_request is True
    assert label_request.label_name == "sign-off: create pr"
    assert sync_request.issue_number == 42
    assert sync_request.head_sha == "head-2"
    assert sync_request.event_created_at == "2026-03-17T10:05:00Z"


def test_runtime_typed_config_accessors_read_runtime_config(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    monkeypatch.setenv("STATE_ISSUE_NUMBER", "77")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_API_RETRY_LIMIT", "9")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_RETRY_SECONDS", "3.5")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_MAX_WAIT_SECONDS", "180")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_TTL_SECONDS", "600")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS", "90")
    monkeypatch.setenv("REVIEWER_BOT_STATE_READ_RETRY_LIMIT", "8")
    monkeypatch.setenv("REVIEWER_BOT_STATE_READ_RETRY_SECONDS", "1.5")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_REF_NAME", "heads/test-lock")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", "develop")

    assert runtime.state_issue_number() == 77
    assert runtime.lock_api_retry_limit() == 9
    assert runtime.lock_retry_base_seconds() == 3.5
    assert runtime.lock_max_wait_seconds() == 180
    assert runtime.lock_lease_ttl_seconds() == 600
    assert runtime.lock_renewal_window_seconds() == 90
    assert runtime.state_read_retry_limit() == 8
    assert runtime.state_read_retry_base_seconds() == 1.5
    assert runtime.lock_ref_name() == "heads/test-lock"
    assert runtime.lock_ref_bootstrap_branch() == "develop"


def test_runtime_accepts_injected_infra_services():
    clock = object()
    sleeper = object()
    jitter = object()
    uuid_source = object()
    logger = object()
    rest_transport = object()
    graphql_transport = object()

    runtime = ReviewerBotRuntime(
        requests=SimpleNamespace(),
        sys=SimpleNamespace(stderr=SimpleNamespace(write=lambda _text: None)),
        random=SimpleNamespace(uniform=lambda lower, upper: lower),
        time=SimpleNamespace(sleep=lambda _seconds: None),
        rest_transport=rest_transport,
        graphql_transport=graphql_transport,
        clock=clock,
        sleeper=sleeper,
        jitter=jitter,
        uuid_source=uuid_source,
        logger=logger,
        state_store=SimpleNamespace(load_state=lambda **kwargs: {}, save_state=lambda state: True),
        github=SimpleNamespace(github_api=lambda *args, **kwargs: {}, github_api_request=lambda *args, **kwargs: {}),
        locks=SimpleNamespace(),
        handlers=SimpleNamespace(),
        adapters=SimpleNamespace(),
    )

    assert runtime.clock is clock
    assert runtime.sleeper is sleeper
    assert runtime.jitter is jitter
    assert runtime.uuid_source is uuid_source
    assert runtime.logger is logger
    assert runtime.rest_transport is rest_transport
    assert runtime.graphql_transport is graphql_transport


def test_runtime_exposes_explicit_infra_and_domain_service_groups():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.infra.config is runtime.config
    assert runtime.infra.outputs is runtime.outputs
    assert runtime.infra.deferred_payloads is runtime.deferred_payloads
    assert runtime.infra.rest_transport is runtime.rest_transport
    assert runtime.infra.graphql_transport is runtime.graphql_transport
    assert runtime.infra.artifact_download_transport is runtime.artifact_download_transport
    assert runtime.infra.clock is runtime.clock
    assert runtime.infra.sleeper is runtime.sleeper
    assert runtime.infra.jitter is runtime.jitter
    assert runtime.infra.uuid_source is runtime.uuid_source
    assert runtime.infra.logger is runtime.logger
    assert runtime.infra.touch_tracker is runtime.touch_tracker
    assert runtime.domain.state_store is runtime.state_store
    assert runtime.domain.github is runtime.github
    assert runtime.domain.locks is runtime.locks
    assert runtime.domain.handlers is runtime.handlers


def test_bootstrap_runtime_wires_explicit_config_output_and_deferred_services():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.config is runtime.infra.config
    assert runtime.outputs is runtime.infra.outputs
    assert runtime.deferred_payloads is runtime.infra.deferred_payloads


def test_bootstrap_runtime_wires_explicit_state_github_and_lock_services():
    runtime = reviewer_bot._runtime_bot()

    assert hasattr(runtime.locks, "acquire")
    assert hasattr(runtime.locks, "release")
    assert hasattr(runtime.locks, "refresh")
    assert hasattr(runtime.state_store, "load_state")
    assert hasattr(runtime.state_store, "save_state")
    assert hasattr(runtime.github, "github_api")
    assert hasattr(runtime.github, "github_api_request")


def test_bootstrap_runtime_wires_explicit_handler_services():
    runtime = reviewer_bot._runtime_bot()

    assert hasattr(runtime.handlers, "handle_issue_or_pr_opened")
    assert hasattr(runtime.handlers, "handle_comment_event")
    assert hasattr(runtime.handlers, "handle_workflow_run_event") is False


def test_bootstrap_runtime_wires_explicit_adapter_services():
    runtime = reviewer_bot._runtime_bot()

    assert hasattr(runtime.adapters, "github")
    assert hasattr(runtime.adapters, "review_state")
    assert hasattr(runtime.adapters, "commands")
    assert hasattr(runtime.adapters, "queue")
    assert hasattr(runtime.adapters, "workflow")
    assert hasattr(runtime.adapters, "automation")
    assert hasattr(runtime.adapters, "state_lock")
    assert runtime.adapters.github is runtime.github
    assert hasattr(runtime.adapters.github, "get_github_token")
    assert hasattr(runtime.adapters.review_state, "ensure_review_entry")
    assert hasattr(runtime.adapters.commands, "handle_pass_command")
    assert hasattr(runtime.adapters.queue, "get_next_reviewer")
    assert hasattr(runtime.adapters.state_lock, "render_state_issue_body")


def test_status_label_sync_contract_stays_on_workflow_adapter_surface():
    runtime = reviewer_bot._runtime_bot()

    assert hasattr(runtime.adapters.workflow, "sync_status_labels_for_items")
    assert hasattr(runtime, "list_open_items_with_status_labels") is False


def _load_runtime_surface_inventory() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/runtime_surface/triple_inventory.json").read_text(
            encoding="utf-8"
        )
    )


def test_f2a_runtime_surface_inventory_fixture_records_retained_triples():
    inventory = _load_runtime_surface_inventory()

    assert inventory["harness_id"] == "F2a runtime/bootstrap/fake-runtime triple inventory"
    assert inventory["artifact_classification"] == "active migration proof fixture"
    assert inventory["proof_artifacts"]
    assert all(entry["classification"] == "rewritten final proof" for entry in inventory["proof_artifacts"])
    capabilities = {entry["capability"]: entry for entry in inventory["capability_triples"]}

    assert capabilities["comment-event dispatch"]["classification"] == "retained final surface"
    assert capabilities["typed REST request result"]["classification"] == "retained final surface"
    assert capabilities["typed assignment helper result"]["classification"] == "retained final surface"
    assert capabilities["reviewer-board GraphQL metadata read"]["classification"] == "retained final surface"
    assert "workflow-run dispatch" not in capabilities
    assert "refresh reviewer review from live preferred review" not in capabilities
    assert "repair missing reviewer review state" not in capabilities
    assert capabilities["privileged pull request creation"]["classification"] == "retained final surface"
    assert "github timestamp parsing" not in capabilities


def test_f2a_runtime_surface_inventory_matches_bootstrap_adapter_examples():
    inventory = _load_runtime_surface_inventory()
    capabilities = {entry["capability"]: entry for entry in inventory["capability_triples"]}

    assert capabilities["comment-event dispatch"]["bootstrap_adapter"].endswith("handle_comment_event")
    assert "workflow-run dispatch" not in capabilities
    assert capabilities["sync status labels"]["bootstrap_adapter"].endswith(
        "sync_status_labels_for_items"
    )
    assert capabilities["rebuild approval state"]["runtime_forwarder"].endswith(
        "rebuild_pr_approval_state"
    )
    assert capabilities["rebuild approval state"]["bootstrap_adapter"].endswith(
        "rebuild_pr_approval_state"
    )
    assert capabilities["mandatory approver satisfaction"]["bootstrap_adapter"].endswith(
        "satisfy_mandatory_approver_requirement"
    )
    assert capabilities["typed REST request result"]["bootstrap_adapter"].endswith("github_api_request")
    assert capabilities["typed assignment helper result"]["bootstrap_adapter"].endswith(
        "request_pr_reviewer_assignment"
    )
    assert capabilities["reviewer-board GraphQL metadata read"]["bootstrap_adapter"].endswith(
        "github_graphql_request"
    )


def test_f2c_no_runtime_surface_triples_are_deletion_ready_yet():
    inventory = _load_runtime_surface_inventory()

    deletion_ready = [
        entry for entry in inventory["capability_triples"] if entry["classification"] == "zero-caller deletion candidate"
    ]

    assert deletion_ready == []


def test_default_stderr_logger_renders_message_and_sorted_fields():
    writes = []
    logger = StdErrLogger(SimpleNamespace(stderr=SimpleNamespace(write=lambda text: writes.append(text))))

    logger.event("warning", "retrying request", retry_attempt=2, issue_number=42)

    assert writes == ["[warning] retrying request issue_number=42 retry_attempt=2\n"]
