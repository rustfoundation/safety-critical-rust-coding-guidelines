from scripts.reviewer_bot_lib import events
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


def test_is_pr_event_reads_runtime_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("IS_PULL_REQUEST", "true")

    assert events._is_pr_event(runtime) is True


def test_require_v18_for_pr_safe_noops_before_epoch_flip(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("IS_PULL_REQUEST", "true")

    assert events._require_v18_for_pr(runtime, {"freshness_runtime_epoch": "legacy_v14"}, "review-event") is False


def test_require_legacy_for_legacy_pr_safe_noops_after_epoch_flip(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("IS_PULL_REQUEST", "true")

    assert events._require_legacy_for_legacy_pr(runtime, {"freshness_runtime_epoch": "freshness_v15"}, "review-event") is False


def test_handle_pull_request_review_event_collects_touched_item_and_defers(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("EVENT_ACTION", "submitted")

    changed = events.handle_pull_request_review_event(runtime, {"freshness_runtime_epoch": "legacy_v14"})

    assert changed is False
    assert runtime.drain_touched_items() == [42]


def test_handle_pull_request_review_event_safe_noops_after_epoch_flip(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("EVENT_ACTION", "dismissed")

    changed = events.handle_pull_request_review_event(runtime, {"freshness_runtime_epoch": "freshness_v15"})

    assert changed is False
    assert runtime.drain_touched_items() == [42]


def test_handle_pull_request_review_event_ignores_unsupported_actions(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("EVENT_ACTION", "edited")

    changed = events.handle_pull_request_review_event(runtime, {"freshness_runtime_epoch": "legacy_v14"})

    assert changed is False
    assert runtime.drain_touched_items() == [42]
