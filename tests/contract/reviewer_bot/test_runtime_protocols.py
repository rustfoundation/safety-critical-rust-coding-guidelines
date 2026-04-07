import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
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


def test_o3_runtime_deletion_manifest_forbids_dead_workflow_run_handler_compatibility_surface():
    manifest = json.loads(
        Path("tests/fixtures/equivalence/runtime_surface/deletion_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["harness_id"] == "O3 runtime compatibility deletion manifest"
    assert "scripts/reviewer_bot_lib/bootstrap_runtime.py:_BootstrapHandlerServices.handle_workflow_run_event" in manifest["deleted_paths"]
    assert "tests/fixtures/fake_runtime.py:FakeReviewerBotRuntime.handle_workflow_run_event" in manifest["deleted_paths"]
