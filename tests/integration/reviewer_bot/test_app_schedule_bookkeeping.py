from pathlib import Path

import pytest

from scripts.reviewer_bot_lib import maintenance, review_state
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration

def test_execute_run_schedule_sweeper_bookkeeping_only_mutation_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    save_calls = []

    def fake_sweep(bot, current):
        current["active_reviews"]["42"].setdefault("reconciled_source_events", []).append(
            "pull_request_review:500"
        )
        return True

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    def fake_schedule_result(bot, current):
        fake_sweep(bot, current)
        return maintenance.ScheduleHandlerResult(True, [], False, None)

    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(lambda current: save_calls.append(list(current["active_reviews"]["42"]["reconciled_source_events"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_calls == [["pull_request_review:500"]]

def test_execute_run_schedule_reviewer_review_activity_only_repair_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["reviewer_review"] = {
        "accepted": {
            "semantic_key": "pull_request_review:10",
            "timestamp": "2026-03-17T10:01:00Z",
            "actor": "alice",
            "reviewed_head_sha": "head-1",
            "source_precedence": 1,
            "payload": {},
        },
        "seen_keys": ["pull_request_review:10"],
    }
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"

    save_calls = []

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return GitHubApiResult(
                200,
                {"state": "open", "head": {"sha": "head-1"}},
                {},
                "ok",
                True,
                None,
                0,
                None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return GitHubApiResult(
                200,
                [
                    {
                        "id": 10,
                        "state": "COMMENTED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "alice"},
                    }
                ],
                {},
                "ok",
                True,
                None,
                0,
                None,
            )
        raise AssertionError(endpoint)

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    def fake_schedule_result(bot, current):
        current_review = current["active_reviews"]["42"]
        current_review["last_reviewer_activity"] = "2026-03-17T10:01:00Z"
        current_review["transition_warning_sent"] = None
        current_review["transition_notice_sent_at"] = None
        return maintenance.ScheduleHandlerResult(True, [], False, None)

    monkeypatch.setattr(maintenance, "handle_scheduled_check_result", fake_schedule_result)
    harness.stub_save_state(
        lambda current: save_calls.append(
            {
                "last_reviewer_activity": current["active_reviews"]["42"]["last_reviewer_activity"],
                "transition_warning_sent": current["active_reviews"]["42"]["transition_warning_sent"],
                "transition_notice_sent_at": current["active_reviews"]["42"]["transition_notice_sent_at"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = harness.run_execute()

    assert result.exit_code == 0
    assert save_calls == [
        {
            "last_reviewer_activity": "2026-03-17T10:01:00Z",
            "transition_warning_sent": None,
            "transition_notice_sent_at": None,
        }
    ]


def test_m2_schedule_handler_exposes_typed_result_shape():
    maintenance_text = Path("scripts/reviewer_bot_lib/maintenance.py").read_text(encoding="utf-8")

    assert "class ScheduleHandlerResult:" in maintenance_text
    for field in ["state_changed", "touched_items", "projection_followup_needed", "projection_failure_message"]:
        assert field in maintenance_text
