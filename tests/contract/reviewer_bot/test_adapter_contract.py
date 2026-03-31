from typing import get_type_hints

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.context import (
    GitHubTransportContext,
    LeaseLockContext,
    ReviewerBotContext,
    StateStoreContext,
)
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime


def test_reviewer_bot_exports_runtime_modules():
    assert reviewer_bot.requests is not None
    assert reviewer_bot.sys is not None
    assert reviewer_bot.datetime is not None
    assert reviewer_bot.timezone is not None


def test_reviewer_bot_satisfies_runtime_context_protocol():
    assert isinstance(reviewer_bot, ReviewerBotContext)


def test_reviewer_bot_satisfies_narrower_lock_and_state_protocols():
    assert isinstance(reviewer_bot, GitHubTransportContext)
    assert isinstance(reviewer_bot, StateStoreContext)
    assert isinstance(reviewer_bot, LeaseLockContext)


def test_render_lock_commit_message_uses_direct_json_import():
    rendered = reviewer_bot.render_lock_commit_message({"lock_state": "unlocked"})
    assert reviewer_bot.LOCK_COMMIT_MARKER in rendered


def test_maybe_record_head_observation_repair_wrapper_exports_structured_result_type():
    hints = get_type_hints(reviewer_bot.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult


def test_runtime_context_protocol_exposes_structured_head_repair_contract():
    hints = get_type_hints(ReviewerBotContext.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult


def test_runtime_bot_returns_concrete_runtime_object():
    runtime = reviewer_bot._runtime_bot()

    assert isinstance(runtime, ReviewerBotRuntime)
    assert runtime.EVENT_INTENT_MUTATING == reviewer_bot.EVENT_INTENT_MUTATING
