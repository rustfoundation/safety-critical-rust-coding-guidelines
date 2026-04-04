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


def test_fake_runtime_satisfies_app_execution_runtime_protocol(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)

    assert isinstance(runtime, AppEventContextRuntime)
    assert isinstance(runtime, AppExecutionRuntime)
    assert isinstance(runtime, EventInputsContext)
