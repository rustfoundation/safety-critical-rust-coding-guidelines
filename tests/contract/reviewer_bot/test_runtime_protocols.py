import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import events, lifecycle
from scripts.reviewer_bot_lib.context import (
    AppEventContextRuntime,
    AppExecutionRuntime,
    EventHandlerContext,
    EventInputsContext,
    ProjectBoardMetadataContext,
    ProjectBoardProjectionContext,
    ReconcileRectifyRuntimeContext,
    ReconcileWorkflowRuntimeContext,
)
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def _assert_core_runtime_surface(runtime) -> None:
    assert hasattr(runtime, "get_config_value")
    assert hasattr(runtime, "infra")
    assert hasattr(runtime, "domain")
    assert runtime.infra.config is runtime.config
    assert runtime.infra.logger is runtime.logger
    assert runtime.infra.rest_transport is runtime.rest_transport
    assert runtime.infra.graphql_transport is runtime.graphql_transport
    assert runtime.infra.artifact_download_transport is runtime.artifact_download_transport
    assert runtime.domain.state_store is runtime.state_store
    assert runtime.domain.github is runtime.github
    assert runtime.domain.locks is runtime.locks
    assert runtime.domain.handlers is runtime.handlers


def test_runtime_bot_returns_concrete_runtime_object():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReviewerBotRuntime)
    assert runtime.EVENT_INTENT_MUTATING == reviewer_bot._runtime_bot().EVENT_INTENT_MUTATING


def test_runtime_object_satisfies_runtime_context_protocols():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)
    assert isinstance(runtime, EventInputsContext)
    assert isinstance(runtime, EventHandlerContext)
    assert isinstance(runtime, ProjectBoardMetadataContext)
    assert isinstance(runtime, ProjectBoardProjectionContext)
    assert isinstance(runtime, ReconcileWorkflowRuntimeContext)
    assert isinstance(runtime, ReconcileRectifyRuntimeContext)
    _assert_core_runtime_surface(runtime)


def test_fake_runtime_satisfies_app_execution_runtime_protocol(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)
    assert isinstance(runtime, EventInputsContext)
    assert isinstance(runtime, ReconcileWorkflowRuntimeContext)
    assert isinstance(runtime, ReconcileRectifyRuntimeContext)
    _assert_core_runtime_surface(runtime)


def test_pr_review_handler_wiring_routes_fake_and_bootstrap_runtimes_to_events_owner(monkeypatch):
    fake_runtime = FakeReviewerBotRuntime(monkeypatch)
    bootstrap_runtime = reviewer_bot._runtime_bot()
    calls = []

    def record_events_owner(bot, state):
        calls.append((bot, state))
        return bot is fake_runtime

    def unexpected_lifecycle_owner(*_args, **_kwargs):
        raise AssertionError("pull_request_review handlers must route through events")

    monkeypatch.setattr(events, "handle_pull_request_review_event", record_events_owner)
    monkeypatch.setattr(lifecycle, "handle_pull_request_review_event", unexpected_lifecycle_owner, raising=False)

    assert fake_runtime.handlers.handle_pull_request_review_event({"owner": "fake"}) is True
    assert bootstrap_runtime.handlers.handle_pull_request_review_event({"owner": "bootstrap"}) is False
    assert [bot for bot, _state in calls] == [fake_runtime, bootstrap_runtime]


def test_o3_runtime_deletion_manifest_forbids_dead_workflow_run_handler_compatibility_surface():
    manifest = json.loads(
        Path("tests/fixtures/equivalence/runtime_surface/deletion_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["harness_id"] == "O3 runtime compatibility deletion manifest"
    assert manifest["artifact_classification"] == "active migration proof fixture"
    assert manifest["proof_artifacts"] == [
        {
            "path": "tests/contract/reviewer_bot/test_runtime_protocols.py",
            "classification": "rewritten final proof",
        },
        {
            "path": "tests/contract/reviewer_bot/test_adapter_contract.py",
            "classification": "rewritten final proof",
        },
        {
            "path": "tests/contract/reviewer_bot/test_fake_runtime_contract.py",
            "classification": "rewritten final proof",
        },
    ]
    recorded_paths = {entry["path"] for entry in manifest["paths"]}
    assert recorded_paths >= {
        "scripts/reviewer_bot_lib/context.py",
        "scripts/reviewer_bot_lib/bootstrap_runtime.py",
        "tests/fixtures/fake_runtime.py",
        "tests/fixtures/focused_fake_services.py",
    }
    assert "scripts/reviewer_bot_lib/bootstrap_runtime.py:_BootstrapHandlerServices.handle_workflow_run_event" in manifest["deleted_paths"]
    assert "tests/fixtures/fake_runtime.py:FakeReviewerBotRuntime.handle_workflow_run_event" in manifest["deleted_paths"]
