import json
from copy import deepcopy
from pathlib import Path

from scripts.reviewer_bot_core import review_state_machine
from scripts.reviewer_bot_lib import review_state, reviews
from tests.fixtures.reviewer_bot import make_state


def _load_review_state_fixture(name: str) -> dict:
    return json.loads(
        Path(f"tests/fixtures/equivalence/review_state/{name}").read_text(encoding="utf-8")
    )


def test_review_state_equivalence_harness_shell_and_fixture_inventory_exist():
    assert Path("tests/fixtures/equivalence/review_state/api_inventory.md").exists()
    assert Path("tests/fixtures/equivalence/review_state/local_state_only_scenarios.json").exists()
    assert Path("tests/fixtures/equivalence/review_state/live_read_assisted_scenarios.json").exists()


def test_review_state_equivalence_harness_shell_documents_future_scope():
    module_text = Path("tests/unit/reviewer_bot/test_review_state_equivalence.py").read_text(
        encoding="utf-8"
    )

    assert "local_state_only_scenarios.json" in module_text
    assert "live_read_assisted_scenarios.json" in module_text


def test_local_state_only_post_deletion_fixture_driven_proof(monkeypatch):
    fixture = _load_review_state_fixture("local_state_only_scenarios.json")
    fixed_now = "2026-03-17T10:00:00+00:00"
    monkeypatch.setattr(review_state_machine, "_now_iso", lambda: fixed_now)

    assert fixture["harness_id"] == "C1b/C1c mutable review-state mutation equivalence"
    assert fixture["scope"] == "local-state-only mutation"

    scenarios = [
        (
            "ensure_review_entry_create",
            lambda state: review_state.ensure_review_entry(state, 42, create=True),
            lambda state: review_state_machine.ensure_review_entry(state, 42, create=True),
            make_state(),
        ),
        (
            "ensure_review_entry_sparse_list_upgrade",
            lambda state: review_state.ensure_review_entry(state, 42, create=False),
            lambda state: review_state_machine.ensure_review_entry(state, 42, create=False),
            {**make_state(), "active_reviews": {"42": ["alice"]}},
        ),
        (
            "accept_channel_event_precedence",
            lambda state: review_state.accept_channel_event(
                state["active_reviews"]["42"],
                "reviewer_comment",
                semantic_key="issue_comment:101",
                timestamp="2026-03-17T11:00:00Z",
                actor="alice",
                source_precedence=2,
                payload={"kind": "comment"},
            ),
            lambda state: review_state_machine.accept_channel_event(
                state["active_reviews"]["42"],
                "reviewer_comment",
                semantic_key="issue_comment:101",
                timestamp="2026-03-17T11:00:00Z",
                actor="alice",
                source_precedence=2,
                payload={"kind": "comment"},
            ),
            {**make_state(), "active_reviews": {"42": {"reviewer_comment": {"accepted": None, "seen_keys": []}}}},
        ),
        (
            "record_reviewer_activity_clears_transition_timers",
            lambda state: review_state.record_reviewer_activity(
                state["active_reviews"]["42"], "2026-03-17T11:00:00Z"
            ),
            lambda state: review_state_machine.record_reviewer_activity(
                state["active_reviews"]["42"], "2026-03-17T11:00:00Z"
            ),
            {
                **make_state(),
                "active_reviews": {
                    "42": {
                        "last_reviewer_activity": "2026-03-17T10:00:00Z",
                        "transition_warning_sent": "2026-03-17T10:30:00Z",
                        "transition_notice_sent_at": "2026-03-17T10:45:00Z",
                    }
                },
            },
        ),
        (
            "record_transition_notice_sent",
            lambda state: review_state.record_transition_notice_sent(
                state["active_reviews"]["42"], "2026-03-17T12:00:00Z"
            ),
            lambda state: review_state_machine.record_transition_notice_sent(
                state["active_reviews"]["42"], "2026-03-17T12:00:00Z"
            ),
            {**make_state(), "active_reviews": {"42": {}}},
        ),
        (
            "set_current_reviewer_resets_cycle_local_fields",
            lambda state: review_state.set_current_reviewer(
                state, 42, "alice", assignment_method="manual"
            ),
            lambda state: review_state_machine.set_current_reviewer(
                state, 42, "alice", assignment_method="manual"
            ),
            {
                **make_state(),
                "active_reviews": {
                    "42": {
                        "pending_privileged_commands": {"issue_comment:10": {"status": "pending"}},
                        "current_cycle_completion": {"completed": True},
                        "current_cycle_write_approval": {"approved": True},
                    }
                },
            },
        ),
        (
            "update_reviewer_activity_case_insensitive",
            lambda state: review_state.update_reviewer_activity(state, 42, "ALICE"),
            lambda state: review_state_machine.update_reviewer_activity(state, 42, "ALICE"),
            {**make_state(), "active_reviews": {"42": {"current_reviewer": "alice"}}},
        ),
        (
            "mark_review_complete",
            lambda state: review_state.mark_review_complete(state, 42, "alice", "unit-test"),
            lambda state: review_state_machine.mark_review_complete(state, 42, "alice", "unit-test"),
            make_state(),
        ),
        (
            "semantic_key_seen_materializes_channel_map",
            lambda state: review_state.semantic_key_seen(
                state["active_reviews"]["42"], "reviewer_comment", "issue_comment:100"
            ),
            lambda state: review_state_machine.semantic_key_seen(
                state["active_reviews"]["42"], "reviewer_comment", "issue_comment:100"
            ),
            {**make_state(), "active_reviews": {"42": {}}},
        ),
    ]

    for scenario_name, delegated, owner, initial_state in scenarios:
        delegated_state = deepcopy(initial_state)
        owner_state = deepcopy(initial_state)

        delegated_result = delegated(delegated_state)
        owner_result = owner(owner_state)

        assert delegated_result == owner_result, scenario_name
        assert delegated_state == owner_state, scenario_name


def test_get_current_cycle_boundary_post_deletion_fixture_driven_proof():
    fixture = _load_review_state_fixture("local_state_only_scenarios.json")

    class Bot:
        @staticmethod
        def parse_iso8601_timestamp(value):
            return reviews.parse_github_timestamp(value)

    review_data = {
        "active_cycle_started_at": None,
        "cycle_started_at": "2026-03-17T09:00:00Z",
        "assigned_at": "2026-03-17T08:00:00Z",
    }

    assert fixture["scope"] == "local-state-only mutation"
    assert review_state.get_current_cycle_boundary(Bot(), deepcopy(review_data)) == review_state_machine.get_current_cycle_boundary(
        Bot(),
        deepcopy(review_data),
    )


def test_live_read_assisted_post_deletion_fixture_driven_proof(monkeypatch):
    fixture = _load_review_state_fixture("live_read_assisted_scenarios.json")

    class Bot:
        def __init__(self):
            self.pull_request_result = {"ok": True, "pull_request": {"head": {"sha": "head-1"}}}
            self.preferred_review = {
                "id": 10,
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }

        @staticmethod
        def parse_iso8601_timestamp(value):
            return reviews.parse_github_timestamp(value)

    monkeypatch.setattr(reviews, "_pull_request_read_result", lambda bot, issue_number: bot.pull_request_result)
    monkeypatch.setattr(
        reviews,
        "get_preferred_current_reviewer_review_for_cycle",
        lambda bot, issue_number, review_data, **kwargs: bot.preferred_review,
    )

    assert fixture["harness_id"] == "C1b/C1c mutable review-state mutation equivalence"
    assert fixture["scope"] == "live-read-assisted mutation"

    delegated_review = {
        "current_reviewer": "alice",
        "reviewer_review": {"accepted": None, "seen_keys": []},
        "last_reviewer_activity": None,
        "transition_warning_sent": None,
        "transition_notice_sent_at": None,
    }
    owner_review = deepcopy(delegated_review)
    delegated_bot = Bot()
    owner_bot = Bot()

    assert review_state.accept_reviewer_review_from_live_review(
        delegated_review,
        delegated_bot.preferred_review,
        actor="alice",
    ) == review_state_machine.accept_reviewer_review_from_live_review(
        owner_review,
        owner_bot.preferred_review,
        actor="alice",
    )
    assert delegated_review == owner_review

    delegated_review = {
        "current_reviewer": "alice",
        "reviewer_review": {"accepted": None, "seen_keys": []},
        "last_reviewer_activity": None,
        "transition_warning_sent": None,
        "transition_notice_sent_at": None,
    }
    owner_review = deepcopy(delegated_review)
    assert review_state.refresh_reviewer_review_from_live_preferred_review(
        delegated_bot,
        42,
        delegated_review,
    ) == review_state_machine.refresh_reviewer_review_from_live_preferred_review(
        owner_bot,
        42,
        owner_review,
    )
    assert delegated_review == owner_review

    delegated_review = deepcopy(delegated_review)
    owner_review = deepcopy(owner_review)
    assert review_state.repair_missing_reviewer_review_state(
        delegated_bot,
        42,
        delegated_review,
    ) == review_state_machine.repair_missing_reviewer_review_state(
        owner_bot,
        42,
        owner_review,
    )
    assert delegated_review == owner_review
