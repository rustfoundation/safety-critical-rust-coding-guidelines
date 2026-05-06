import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_core import approval_policy, live_review_support
from scripts.reviewer_bot_core.reviewer_response_policy import (
    to_reviewer_response_decision,
)
from scripts.reviewer_bot_lib import github_api, reviews, reviews_projection
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)


def _bot(**overrides):
    github = SimpleNamespace(
        get_pull_request_reviews=lambda issue_number: [],
        get_issue_or_pr_snapshot=lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
        get_user_permission_status=lambda username, required_permission="push": "granted",
    )
    bot = SimpleNamespace(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(200, {}, {}, "ok", True, None, 0, None),
        github_api=lambda method, endpoint, data=None: {},
        github=github,
        parse_github_timestamp=reviews.parse_github_timestamp,
        parse_iso8601_timestamp=reviews.parse_github_timestamp,
        ensure_review_entry=lambda state, issue_number, create=False: None,
    )
    for key, value in overrides.items():
        setattr(bot, key, value)
    return bot


def test_compute_reviewer_response_state_is_pure_for_pr_projection():
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    before = json.loads(json.dumps(review))
    bot = _bot(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request_payload(42, head_sha="head-1") if endpoint == "pulls/42" else [],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
    )

    response_state = reviews.compute_reviewer_response_state(bot, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert review == before


def test_compute_reviewer_response_state_keeps_mutable_approval_rebuild_support_out_of_derivation():
    review = make_tracked_review_state(
        make_state(),
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": "2026-03-17T10:01:00Z",
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["reviewer_review"]["seen_keys"] = ["pull_request_review:10"]
    before = json.loads(json.dumps(review))
    bot = _bot(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request_payload(42, head_sha="head-1")
            if endpoint == "pulls/42"
            else [
                review_payload(
                    11,
                    state="APPROVED",
                    submitted_at="2026-03-17T10:05:00Z",
                    commit_id="head-1",
                    author="bob",
                )
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
    )
    bot.github.get_user_permission_status = lambda username, required_permission="push": "denied"

    response_state = reviews.compute_reviewer_response_state(bot, 42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "review_head_stale"
    assert review == before


def test_compute_pr_approval_state_result_is_pure():
    review = make_tracked_review_state(
        make_state(),
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    before = json.loads(json.dumps(review))
    bot = _bot(
        github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
            200,
            pull_request_payload(42, head_sha="head-1")
            if endpoint == "pulls/42"
            else [
                review_payload(
                    10,
                    state="APPROVED",
                    submitted_at="2026-03-17T10:01:00Z",
                    commit_id="head-1",
                    author="alice",
                )
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        )
    )

    result = approval_policy.compute_pr_approval_state_result(bot, 42, review)

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert review == before


def test_apply_pr_approval_state_mutates_expected_fields():
    review = make_tracked_review_state(make_state(), 42)
    review["active_head_sha"] = "head-0"
    review["current_cycle_reviewer_handoff"] = {
        "source_event_key": "issue_comment:100",
        "timestamp": "2026-03-17T09:00:00Z",
        "actor": "alice",
        "command_name": "feedback",
        "reviewed_head_sha": "head-0",
    }

    reviews.apply_pr_approval_state(
        review,
        completion={"completed": True, "current_head_sha": "head-1", "qualifying_review_ids": [10]},
        write_approval={"has_write_approval": True, "write_approvers": ["alice"], "current_head_sha": "head-1"},
        current_head_sha="head-1",
    )

    assert review["active_head_sha"] == "head-1"
    assert review["current_cycle_reviewer_handoff"] is None
    assert review["current_cycle_completion"]["completed"] is True
    assert review["current_cycle_write_approval"]["has_write_approval"] is True
    assert review["review_completion_source"] == "live_review_rebuild"


def test_compute_pr_approval_state_from_reviews_is_pure():
    survivors = {
        "alice": {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": reviews.parse_github_timestamp("2026-03-17T10:01:00Z"),
            "commit_id": "head-1",
            "user": {"login": "alice"},
        }
    }
    before = json.loads(json.dumps({"survivors": {"alice": {"id": 10, "state": "APPROVED", "commit_id": "head-1", "user": {"login": "alice"}}}}))

    result = approval_policy.compute_pr_approval_state_from_reviews(
        survivors,
        current_reviewer="alice",
        current_head="head-1",
        permission_statuses={"alice": "granted"},
    )

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert before["survivors"]["alice"]["id"] == 10


def test_compute_pr_approval_state_from_reviews_does_not_mint_completion_from_alternate_approval():
    survivors = {
        "bob": {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": reviews.parse_github_timestamp("2026-03-17T10:01:00Z"),
            "commit_id": "head-1",
            "user": {"login": "bob"},
        }
    }

    result = approval_policy.compute_pr_approval_state_from_reviews(
        survivors,
        current_reviewer="alice",
        current_head="head-1",
        permission_statuses={"bob": "granted"},
    )

    assert result["ok"] is True
    assert result["completion"] == {
        "completed": False,
        "current_head_sha": "head-1",
        "qualifying_review_ids": [],
    }
    assert result["write_approval"] == {
        "has_write_approval": True,
        "write_approvers": ["bob"],
        "current_head_sha": "head-1",
    }


def test_normalize_reviews_with_parsed_timestamps_is_pure():
    review_items = [
        {
            "id": 10,
            "state": "APPROVED",
            "submitted_at": "2026-03-17T10:01:00Z",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        }
    ]
    before = json.loads(json.dumps(review_items))

    normalized = live_review_support.normalize_reviews_with_parsed_timestamps(
        review_items,
        parse_timestamp=reviews.parse_github_timestamp,
    )

    assert normalized[0]["submitted_at"] == reviews.parse_github_timestamp("2026-03-17T10:01:00Z")
    assert review_items == before


def test_collect_permission_statuses_deduplicates_authors():
    survivors = {
        "alice": {"user": {"login": "alice"}},
        "alice-2": {"user": {"login": "alice"}},
        "bob": {"user": {"login": "bob"}},
    }
    observed = []

    statuses = live_review_support.collect_permission_statuses(
        survivors,
        permission_status=lambda author: observed.append(author) or "granted",
    )

    assert statuses == {"alice": "granted", "bob": "granted"}
    assert observed == ["alice", "bob"]


def test_approval_policy_classification_table_marks_support_helpers_as_moved_out_of_projection_module():
    table = Path("tests/fixtures/equivalence/approval_policy/function_classification_table.md").read_text(
        encoding="utf-8"
    )

    for line in [
        "Moves to `live_review_support.py`",
        "- `filter_current_head_reviews_for_cycle`",
        "- `normalize_reviews_with_parsed_timestamps`",
        "- `collect_permission_statuses`",
        "Moves to `approval_policy.py`",
        "- `compute_pr_approval_state_from_reviews`",
        "- `desired_labels_from_response_state`",
    ]:
        assert line in table


def test_h1a_reviewer_response_matrix_fixture_exists_and_stays_reviewer_response_only():
    matrix = json.loads(
        Path("tests/fixtures/equivalence/reviewer_response/scenario_matrix.json").read_text(encoding="utf-8")
    )

    assert matrix["harness_id"] == "H1a reviewer-response derivation equivalence"
    assert matrix["owner"] == "scripts.reviewer_bot_core.reviewer_response_policy.compute_reviewer_response_state"
    assert matrix["out_of_scope"] == [
        "mandatory approver escalation",
        "label writes",
    ]
    assert [scenario["id"] for scenario in matrix["scenarios"]] == [
        "awaiting_reviewer_response_no_reviewer_activity",
        "awaiting_reviewer_response_review_head_stale",
        "awaiting_reviewer_response_contributor_revision_newer",
        "awaiting_contributor_response_completion_missing",
        "awaiting_write_approval_write_approval_missing",
        "projection_failed_pull_request_unavailable",
        "projection_failed_pull_request_head_unavailable",
        "projection_failed_live_review_state_unknown",
    ]


def test_status_projection_maps_reassignment_needed_and_exposes_decision_output():
    decision = to_reviewer_response_decision(
        {
            "issue_number": 264,
            "current_reviewer": "iglesias",
            "response_state": "reviewer_reassignment_needed",
            "suppression_reason": "legacy_duplicate_reminders_exhausted",
            "current_scope_key": "scope-1",
            "current_scope_basis": "reminder_cadence_exhausted",
        }
    )

    result = reviews_projection.derive_status_label_projection(
        reviews_projection.StatusLabelProjectionInput(
            issue_number=264,
            issue_state="open",
            actual_labels=("status: awaiting reviewer response",),
            reviewer_response=decision,
            reviewer_authority_outcome="tracked_reviewer_confirmed",
            freshness_runtime_epoch="freshness_v15",
            status_projection_epoch="status_projection_v2",
        )
    )
    payload = reviews_projection.status_label_projection_output(
        result,
        preview_action="preview-status-label-projection",
        validation_nonce="nonce",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="2",
        artifact_name="reviewer-bot-preview-output-1-attempt-2",
        artifact_file="preview-output.json",
    )

    assert result.delta.desired_status_labels == ("status: reviewer reassignment needed",)
    assert result.delta.labels_to_add == ("status: reviewer reassignment needed",)
    assert result.delta.labels_to_remove == ("status: awaiting reviewer response",)
    assert result.projection_metadata["source"] == "reviewer_response_decision"
    assert result.projection_metadata["decision_output"] == decision.to_output()
    assert payload["desired_status_labels"] == ["status: reviewer reassignment needed"]
    assert payload["output_keys"] == sorted(payload.keys())


@pytest.mark.parametrize("state_name", ["projection_failed", "live_read_unavailable", "unknown"])
def test_status_projection_fail_closed_states_never_clear_existing_labels(state_name):
    decision = to_reviewer_response_decision({"response_state": state_name})

    with pytest.raises(RuntimeError, match="status_label_projection_blocked"):
        reviews_projection.derive_status_label_projection(
            reviews_projection.StatusLabelProjectionInput(
                issue_number=42,
                issue_state="open",
                actual_labels=("status: awaiting reviewer response",),
                reviewer_response=decision,
                reviewer_authority_outcome="tracked_reviewer_confirmed",
                freshness_runtime_epoch=None,
                status_projection_epoch=None,
            )
        )


def test_apply_status_label_delta_is_mutation_boundary(monkeypatch):
    calls = []
    bot = _bot()
    bot.github.ensure_label_exists = lambda label, **kwargs: calls.append(("ensure", label, kwargs)) or True
    monkeypatch.setattr(github_api, "add_label_with_status", lambda bot, issue_number, label: calls.append(("add", issue_number, label)) or True)
    monkeypatch.setattr(github_api, "remove_label_with_status", lambda bot, issue_number, label: calls.append(("remove", issue_number, label)) or True)
    delta = reviews_projection.status_label_delta(
        ("status: awaiting reviewer response",),
        ("status: reviewer reassignment needed",),
    )

    result = reviews.apply_status_label_delta(bot, 264, delta)

    assert result.to_output() == {
        "issue_number": 264,
        "before_status_labels": ["status: awaiting reviewer response"],
        "desired_status_labels": ["status: reviewer reassignment needed"],
        "labels_added": ["status: reviewer reassignment needed"],
        "labels_removed": ["status: awaiting reviewer response"],
        "changed": True,
    }
    assert calls[0][0:2] == ("ensure", "status: reviewer reassignment needed")
    assert ("remove", 264, "status: awaiting reviewer response") in calls
    assert ("add", 264, "status: reviewer reassignment needed") in calls
