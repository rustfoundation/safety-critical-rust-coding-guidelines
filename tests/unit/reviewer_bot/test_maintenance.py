from scripts.reviewer_bot_lib import lifecycle, maintenance, review_state
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_scheduled_check_repairs_missing_reviewer_review_state(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.get_issue_or_pr_snapshot = lambda issue_number: {"pull_request": {}}
    bot.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
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
    bot.collect_touched_item = lambda issue_number: None
    monkeypatch.setattr(maintenance, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
    monkeypatch.setattr(maintenance, "check_overdue_reviews", lambda bot, state: [])

    assert maintenance.handle_scheduled_check(bot, state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted is not None
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"


def test_scheduled_check_records_live_read_failure_and_continues(monkeypatch):
    state = make_state()
    review_42 = review_state.ensure_review_entry(state, 42, create=True)
    review_43 = review_state.ensure_review_entry(state, 43, create=True)
    assert review_42 is not None and review_43 is not None
    review_42["current_reviewer"] = "alice"
    review_43["current_reviewer"] = "bob"
    overdue_called = []
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.collect_touched_item = lambda issue_number: None
    bot.get_issue_or_pr_snapshot = lambda issue_number: {"pull_request": {}}
    monkeypatch.setattr(maintenance, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance, "check_overdue_reviews", lambda bot, state: overdue_called.append(True) or [])
    monkeypatch.setattr(maintenance, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)

    def fake_head_repair(bot, issue_number, review_data):
        if issue_number == 42:
            return lifecycle.HeadObservationRepairResult(changed=False, outcome="skipped_unavailable", failure_kind="server_error", reason="pull_request_unavailable")
        review_data["repair_needed"] = {
            "kind": "live_read_failure",
            "phase": "head_observation_repair",
            "reason": "stale",
            "failure_kind": "server_error",
            "recorded_at": "2026-03-01T00:00:00Z",
        }
        return lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged")

    monkeypatch.setattr(maintenance, "maybe_record_head_observation_repair", fake_head_repair)

    assert maintenance.handle_scheduled_check(bot, state) is True
    assert overdue_called == [True]
    assert review_42["repair_needed"]["kind"] == "live_read_failure"
    assert review_42["repair_needed"]["phase"] == "head_observation_repair"
    assert review_42["repair_needed"]["failure_kind"] == "server_error"
    assert review_43["repair_needed"] is None


def test_record_maintenance_repair_marker_ignores_recorded_at_for_identical_failure(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    timestamps = iter(["2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"])
    bot = FakeReviewerBotRuntime(monkeypatch)
    monkeypatch.setattr(maintenance, "_now_iso", lambda bot: next(timestamps))

    first = maintenance._record_maintenance_repair_marker(
        bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )
    second = maintenance._record_maintenance_repair_marker(
        bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )

    assert first is True
    assert second is False
    assert review["repair_needed"]["recorded_at"] == "2026-03-01T00:00:00Z"


def test_scheduled_check_clears_head_observation_repair_marker_after_success(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["repair_needed"] = {
        "kind": "live_read_failure",
        "phase": "head_observation_repair",
        "reason": "pull_request_unavailable",
        "failure_kind": "server_error",
        "recorded_at": "2026-03-01T00:00:00Z",
    }
    bot = FakeReviewerBotRuntime(monkeypatch)
    bot.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []}
    monkeypatch.setattr(maintenance, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(maintenance, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)
    monkeypatch.setattr(maintenance, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
    monkeypatch.setattr(maintenance, "check_overdue_reviews", lambda bot, state: [])

    assert maintenance.handle_scheduled_check(bot, state) is True
    assert review["repair_needed"] is None
