import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime
from scripts.reviewer_bot_lib.runtime_protocols import (
    AppEventContextRuntime,
    AppExecutionRuntime,
    EventInputsContext,
    ProjectBoardMetadataContext,
    ProjectBoardProjectionContext,
    ReconcileRectifyRuntimeContext,
    ReconcileWorkflowRuntimeContext,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def _assert_core_runtime_surface(runtime) -> None:
    assert hasattr(runtime, "get_config_value")
    assert hasattr(runtime, "AssignmentAttempt")
    assert hasattr(runtime, "GitHubApiResult")
    assert hasattr(runtime, "COMMANDS")
    assert hasattr(runtime, "REVIEW_LABELS")
    assert hasattr(runtime, "github_graphql_request")
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


def test_fake_runtime_default_lock_state_matches_production_contract(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert runtime.ACTIVE_LEASE_CONTEXT is None


def test_runtime_bot_returns_concrete_runtime_object():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReviewerBotRuntime)
    assert runtime.EVENT_INTENT_MUTATING == reviewer_bot._runtime_bot().EVENT_INTENT_MUTATING


def test_runtime_object_satisfies_runtime_context_protocols():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)
    assert isinstance(runtime, EventInputsContext)
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
    assert manifest["artifact_classification"] == "active migration proof fixture"
    recorded_paths = {entry["path"] for entry in manifest["paths"]}
    assert recorded_paths >= {
        "scripts/reviewer_bot_lib/context.py",
        "scripts/reviewer_bot_lib/bootstrap_runtime.py",
        "tests/fixtures/fake_runtime.py",
        "tests/fixtures/focused_fake_services.py",
    }
    assert manifest["proof_artifacts"]
    assert all(entry["classification"] == "rewritten final proof" for entry in manifest["proof_artifacts"])
    assert all("handle_workflow_run_event" in path for path in manifest["deleted_paths"])
