import pytest

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.integration

def test_execute_run_schedule_sweeper_bookkeeping_only_mutation_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
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
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", fake_sweep)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    monkeypatch.setattr(reviewer_bot.review_state_module, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data, *, reviews=None: False)
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    harness.stub_save_state(lambda current: save_calls.append(list(current["active_reviews"]["42"]["reconciled_source_events"])) or True)
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_calls == [["pull_request_review:500"]]

def test_execute_run_schedule_reviewer_review_activity_only_repair_still_saves_state(monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(EVENT_NAME="schedule", EVENT_ACTION="")
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
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
            return reviewer_bot.GitHubApiResult(
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
            return reviewer_bot.GitHubApiResult(
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
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, current: False)
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, current: [])
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    harness.runtime.github_api_request = fake_github_api_request
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
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

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_calls == [
        {
            "last_reviewer_activity": "2026-03-17T10:01:00Z",
            "transition_warning_sent": None,
            "transition_notice_sent_at": None,
        }
    ]
