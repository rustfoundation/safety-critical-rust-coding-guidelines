from types import SimpleNamespace
from typing import get_type_hints

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import event_inputs, lease_lock, review_state
from scripts.reviewer_bot_lib.context import ReviewerBotContext
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime, StdErrLogger
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_render_lock_commit_message_uses_direct_json_import():
    rendered = lease_lock.render_lock_commit_message(reviewer_bot._runtime_bot(), {"lock_state": "unlocked"})
    assert rendered.startswith("reviewer-bot-lock-v1\n")


def test_build_event_context_returns_structured_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("ISSUE_LABELS", '["coding guideline"]')

    context = reviewer_bot.build_event_context()

    assert context.event_name == "workflow_run"
    assert context.workflow_run_event == "pull_request_review"
    assert context.issue_labels == ("coding guideline",)


def test_execute_run_returns_execution_result(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    runtime = reviewer_bot._runtime_bot()
    monkeypatch.setattr(runtime.state_store, "load_state", lambda *, fail_on_unavailable=False: {"active_reviews": {}})
    monkeypatch.setattr(runtime.handlers, "handle_pull_request_review_event", lambda state: False)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0


def test_entrypoint_helpers_accept_explicit_runtime(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("EVENT_NAME", "issue_comment")
    runtime.set_config_value("EVENT_ACTION", "created")

    context = reviewer_bot.build_event_context(runtime)
    result = reviewer_bot.execute_run(context, runtime)

    assert context.event_name == "issue_comment"
    assert result.exit_code == 0


def test_review_state_owner_exports_mutation_helper():
    hints = get_type_hints(review_state.ensure_review_entry)

    assert hints["return"] == dict | None


def test_runtime_head_repair_contract_is_runtime_scoped():
    hints = get_type_hints(ReviewerBotContext.maybe_record_head_observation_repair)

    assert hints["return"].__name__ == "HeadObservationRepairResult"


def test_runtime_review_state_adapter_mutates_active_reviews():
    state = make_state()
    review = reviewer_bot._runtime_bot().ensure_review_entry(state, 42, create=True)

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


def test_event_inputs_build_comment_request_and_trust_context_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_STATE", "open")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
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
    runtime.set_config_value("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    runtime.set_config_value("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    runtime.set_config_value("GITHUB_REF", "refs/heads/main")
    runtime.set_config_value("GITHUB_RUN_ID", "123")
    runtime.set_config_value("GITHUB_RUN_ATTEMPT", "2")

    request = event_inputs.build_comment_event_request(runtime)
    trust_context = event_inputs.build_pr_comment_trust_context(runtime)

    assert request.issue_number == 42
    assert request.is_pull_request is True
    assert request.comment_id == 100
    assert request.comment_author == "alice"
    assert request.comment_author_id == 200
    assert request.comment_source_event_key == "issue_comment:100"
    assert trust_context.github_repository == "rustfoundation/safety-critical-rust-coding-guidelines"
    assert trust_context.comment_author_association == "MEMBER"
    assert trust_context.current_workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml"
    assert trust_context.github_ref == "refs/heads/main"
    assert trust_context.github_run_id == 123
    assert trust_context.github_run_attempt == 2


def test_event_inputs_build_assignment_and_privileged_requests_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.set_config_value("ISSUE_LABELS", '["fls-audit"]')
    runtime.set_config_value("REPO_OWNER", "rustfoundation")
    runtime.set_config_value("REPO_NAME", "safety-critical-rust-coding-guidelines")
    runtime.set_config_value("REVIEWER_BOT_TARGET_REPO_ROOT", "/tmp/repo")
    runtime.set_config_value("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "42")
    runtime.set_config_value("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "head-1")
    runtime.set_config_value("WORKFLOW_RUN_HEAD_SHA", "head-1")

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
    assert privileged_request.target_repo_root == "/tmp/repo"
    assert privileged_request.workflow_run_reconcile_pr_number == 42
    assert privileged_request.workflow_run_reconcile_head_sha == "head-1"
    assert privileged_request.workflow_run_head_sha == "head-1"


def test_github_api_assignment_helpers_use_runtime_config_for_pr_vs_issue(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    recorded = []

    def fake_request(method, endpoint, data=None, suppress_error_log=True, **kwargs):
        recorded.append((method, endpoint, data))
        return runtime.GitHubApiResult(201, {}, {}, "ok", True, None, 0, None)

    runtime.github_api_request = fake_request

    runtime.set_config_value("IS_PULL_REQUEST", "true")
    github_pr_attempt = reviewer_bot._runtime_bot(runtime).request_reviewer_assignment(42, "alice")

    runtime.set_config_value("IS_PULL_REQUEST", "false")
    github_issue_attempt = reviewer_bot._runtime_bot(runtime).request_reviewer_assignment(42, "alice")

    assert github_pr_attempt.success is True
    assert github_issue_attempt.success is True
    assert recorded == [
        ("POST", "pulls/42/requested_reviewers", {"reviewers": ["alice"]}),
        ("POST", "issues/42/assignees", {"assignees": ["alice"]}),
    ]


def test_event_inputs_parse_labels_and_target_repo_root_from_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_LABELS", '["coding guideline", "fls-audit"]')
    runtime.set_config_value("REVIEWER_BOT_TARGET_REPO_ROOT", "/tmp/repo")

    assert event_inputs.parse_issue_labels(runtime) == ["coding guideline", "fls-audit"]
    assert str(event_inputs.get_target_repo_root(runtime)) == "/tmp/repo"


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
    monkeypatch.setenv("REVIEWER_BOT_LOCK_REF_NAME", "heads/test-lock")
    monkeypatch.setenv("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", "develop")

    assert runtime.state_issue_number() == 77
    assert runtime.lock_api_retry_limit() == 9
    assert runtime.lock_retry_base_seconds() == 3.5
    assert runtime.lock_max_wait_seconds() == 180
    assert runtime.lock_lease_ttl_seconds() == 600
    assert runtime.lock_renewal_window_seconds() == 90
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
    assert runtime.domain.adapters is runtime.adapters


def test_bootstrap_runtime_wires_explicit_config_output_and_deferred_services():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.config is runtime.infra.config
    assert runtime.outputs is runtime.infra.outputs
    assert runtime.deferred_payloads is runtime.infra.deferred_payloads
    assert runtime.config.__class__.__name__ == "_EnvConfig"
    assert runtime.outputs.__class__.__name__ == "_FileOutputSink"
    assert runtime.deferred_payloads.__class__.__name__ == "_JsonDeferredPayloadLoader"


def test_bootstrap_runtime_wires_explicit_state_github_and_lock_services():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.state_store.__class__.__name__ == "_BootstrapStateStoreServices"
    assert runtime.github.__class__.__name__ == "_BootstrapGitHubServices"
    assert runtime.locks.__class__.__name__ == "_BootstrapLockServices"
    assert hasattr(runtime.locks, "acquire")
    assert hasattr(runtime.locks, "release")
    assert hasattr(runtime.locks, "refresh")


def test_bootstrap_runtime_wires_explicit_handler_services():
    runtime = reviewer_bot._runtime_bot()

    assert runtime.handlers.__class__.__name__ == "_BootstrapHandlerServices"
    assert hasattr(runtime.handlers, "handle_issue_or_pr_opened")
    assert hasattr(runtime.handlers, "handle_comment_event")
    assert hasattr(runtime.handlers, "handle_workflow_run_event")


def test_default_stderr_logger_renders_message_and_sorted_fields():
    writes = []
    logger = StdErrLogger(SimpleNamespace(stderr=SimpleNamespace(write=lambda text: writes.append(text))))

    logger.event("warning", "retrying request", retry_attempt=2, issue_number=42)

    assert writes == ["[warning] retrying request issue_number=42 retry_attempt=2\n"]
