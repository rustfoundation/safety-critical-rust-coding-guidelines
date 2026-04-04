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
)
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def _assert_core_runtime_surface(runtime) -> None:
    assert hasattr(runtime, "get_config_value")
    assert hasattr(runtime, "get_github_token")
    assert hasattr(runtime, "get_github_graphql_token")
    assert hasattr(runtime, "rest_transport")
    assert hasattr(runtime, "graphql_transport")
    assert hasattr(runtime, "artifact_download_transport")
    assert hasattr(runtime, "logger")
    assert hasattr(runtime, "fetch_members")
    assert hasattr(runtime, "state_issue_number")
    assert hasattr(runtime, "lock_api_retry_limit")
    assert hasattr(runtime, "lock_retry_base_seconds")
    assert hasattr(runtime, "lock_lease_ttl_seconds")
    assert hasattr(runtime, "lock_max_wait_seconds")
    assert hasattr(runtime, "lock_renewal_window_seconds")
    assert hasattr(runtime, "lock_ref_name")
    assert hasattr(runtime, "lock_ref_bootstrap_branch")
    assert hasattr(runtime, "get_pull_request_reviews")


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
    _assert_core_runtime_surface(runtime)


def test_fake_runtime_satisfies_app_execution_runtime_protocol(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)
    assert isinstance(runtime, EventInputsContext)
    _assert_core_runtime_surface(runtime)
