import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.reviewer_bot_core import (
    live_review_support,
    reviewer_response_policy,
    reviewer_review_helpers,
)
from scripts.reviewer_bot_lib import reviews
from tests.fixtures.reviewer_bot import (
    accept_contributor_revision,
    accept_reviewer_review,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result
from tests.unit.reviewer_bot.test_reviews_live_fetch import _runtime


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/reviewer_response/scenario_matrix.json").read_text(encoding="utf-8")
    )


def _run_scenario(monkeypatch, scenario_id: str) -> dict[str, object]:
    runtime, review = _build_scenario(monkeypatch, scenario_id)
    return reviews.compute_reviewer_response_state(runtime, 42, review)


def _build_scenario(monkeypatch, scenario_id: str):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")

    if scenario_id == "awaiting_reviewer_response_no_reviewer_activity":
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(42, [])
        runtime = _runtime(monkeypatch, routes)
        return runtime, review

    if scenario_id == "awaiting_reviewer_response_review_head_stale":
        accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-2")).add_pull_request_reviews(42, [])
        runtime = _runtime(monkeypatch, routes)
        return runtime, review

    if scenario_id == "awaiting_reviewer_response_contributor_revision_newer":
        accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-17T11:00:00Z", actor="alice", reviewed_head_sha="head-0", source_precedence=1)
        accept_contributor_revision(review, semantic_key="pull_request_sync:42:head-1", timestamp="2026-03-17T12:00:00Z", actor="alice", head_sha="head-1")
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
            42,
            [review_payload(99, state="COMMENTED", submitted_at="2026-03-17T11:00:00Z", commit_id="head-0", author="alice")],
        )
        runtime = _runtime(monkeypatch, routes)
        return runtime, review

    if scenario_id == "awaiting_contributor_response_completion_missing":
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
            42,
            [review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
        )
        runtime = _runtime(monkeypatch, routes)
        monkeypatch.setattr(
            reviews,
            "rebuild_pr_approval_state",
            lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
        )
        return runtime, review

    if scenario_id == "awaiting_write_approval_write_approval_missing":
        accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
            42,
            [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="bob")],
        )
        runtime = _runtime(monkeypatch, routes)
        runtime.get_user_permission_status = lambda username, required_permission="triage": "denied"
        return runtime, review

    if scenario_id == "projection_failed_pull_request_unavailable":
        routes = RouteGitHubApi().add_request("GET", "pulls/42", result=github_result(502, {"message": "bad gateway"}, retry_attempts=1))
        runtime = _runtime(monkeypatch, routes)
        return runtime, review

    if scenario_id == "projection_failed_pull_request_head_unavailable":
        routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {}})
        runtime = _runtime(monkeypatch, routes)
        return runtime, review

    if scenario_id == "projection_failed_live_review_state_unknown":
        accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-17T10:01:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
        routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
            42,
            [review_payload(10, state="APPROVED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice")],
        )
        runtime = _runtime(monkeypatch, routes)
        runtime.get_user_permission_status = lambda username, required_permission="triage": "unavailable"
        return runtime, review

    raise AssertionError(f"Unhandled scenario: {scenario_id}")


def _legacy_compute_reviewer_response_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    issue_snapshot: dict | None = None,
    pull_request: dict | None = None,
    reviews_data: list[dict] | None = None,
) -> dict[str, object]:
    if issue_snapshot is None:
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return {"state": "projection_failed", "reason": "issue_snapshot_unavailable"}
    is_pr = isinstance(issue_snapshot.get("pull_request"), dict)
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return {"state": "untracked", "reason": "no_current_reviewer"}

    reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    contributor_comment = review_data.get("contributor_comment", {}).get("accepted")

    if not is_pr:
        if not reviewer_comment and not reviewer_review:
            return {
                "state": "awaiting_reviewer_response",
                "reason": "no_reviewer_activity",
                "anchor_timestamp": _legacy_initial_reviewer_anchor(review_data),
                "reviewer_comment": reviewer_comment,
                "reviewer_review": reviewer_review,
                "contributor_comment": contributor_comment,
                "contributor_handoff": None,
            }
        latest_reviewer_response = reviewer_comment
        if reviewer_review_helpers.compare_records(
            reviewer_review,
            latest_reviewer_response,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            latest_reviewer_response = reviewer_review
        completion = review_data.get("current_cycle_completion")
        if not isinstance(completion, dict) or not completion.get("completed"):
            if review_data.get("review_completed_at"):
                return {"state": "done", "reason": None}
            return {
                "state": "awaiting_contributor_response",
                "reason": "completion_missing",
                "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            }
        return {"state": "done", "reason": None}

    pull_request_result = live_review_support.read_pull_request_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return {"state": "projection_failed", "reason": str(pull_request_result.get("reason"))}
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return {"state": "projection_failed", "reason": "pull_request_head_unavailable"}

    if not reviewer_comment and not reviewer_review:
        reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews_data)
        if not reviews_result.get("ok"):
            return {"state": "projection_failed", "reason": str(reviews_result.get("reason"))}
        reviews_data = reviews_result["reviews"]
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews_data,
        )
        if preferred_live_review is not None:
            reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
                preferred_live_review,
                actor=current_reviewer,
            )
        else:
            return {
                "state": "awaiting_reviewer_response",
                "reason": "no_reviewer_activity",
                "anchor_timestamp": _legacy_initial_reviewer_anchor(review_data),
                "reviewer_comment": reviewer_comment,
                "reviewer_review": reviewer_review,
                "contributor_comment": contributor_comment,
                "contributor_handoff": None,
            }

    stored_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    refresh_live_review = reviews_data is not None or reviewer_review is None
    if not refresh_live_review:
        refresh_live_review = not isinstance(stored_review_head, str) or stored_review_head != current_head

    preferred_live_review = None
    if refresh_live_review:
        reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews_data)
        if not reviews_result.get("ok"):
            return {"state": "projection_failed", "reason": str(reviews_result.get("reason"))}
        reviews_data = reviews_result["reviews"]
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews_data,
        )
    if preferred_live_review is not None:
        reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
            preferred_live_review,
            actor=current_reviewer,
        )
    elif refresh_live_review:
        reviewer_review = None

    latest_reviewer_response = reviewer_comment
    if reviewer_review_helpers.compare_records(
        reviewer_review,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        latest_reviewer_response = reviewer_review

    contributor_handoff = contributor_comment
    contributor_revision = _legacy_contributor_revision_handoff_record(
        review_data,
        current_head,
        reviewer_review if isinstance(reviewer_review, dict) else None,
    )
    if reviewer_review_helpers.compare_records(
        contributor_revision,
        contributor_handoff,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        contributor_handoff = contributor_revision

    if _legacy_compare_cross_channel_conversation(contributor_handoff, latest_reviewer_response) > 0:
        reason = "contributor_comment_newer"
        if isinstance(contributor_handoff, dict) and str(contributor_handoff.get("semantic_key", "")).startswith("pull_request_"):
            reason = "contributor_revision_newer"
        return {
            "state": "awaiting_reviewer_response",
            "reason": reason,
            "anchor_timestamp": contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }

    latest_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if not isinstance(latest_review_head, str) or latest_review_head != current_head:
        return {
            "state": "awaiting_reviewer_response",
            "reason": "review_head_stale",
            "anchor_timestamp": contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else _legacy_initial_reviewer_anchor(review_data),
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }

    completion, write_approval, approval_failure = reviews.resolve_pr_approval_state(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews_data,
    )
    if completion is None or write_approval is None:
        return {"state": "projection_failed", "reason": approval_failure or "live_review_state_unknown"}
    if not completion.get("completed"):
        return {
            "state": "awaiting_contributor_response",
            "reason": "completion_missing",
            "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }
    if not write_approval.get("has_write_approval"):
        return {
            "state": "awaiting_write_approval",
            "reason": "write_approval_missing",
            "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            "current_head_sha": current_head,
            "reviewer_comment": reviewer_comment,
            "reviewer_review": reviewer_review,
            "contributor_comment": contributor_comment,
            "contributor_handoff": contributor_handoff,
        }
    return {
        "state": "done",
        "reason": "write_approval_present",
        "anchor_timestamp": latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
        "current_head_sha": current_head,
        "reviewer_comment": reviewer_comment,
        "reviewer_review": reviewer_review,
        "contributor_comment": contributor_comment,
        "contributor_handoff": contributor_handoff,
    }


def _legacy_record_timestamp(record: dict | None):
    if not isinstance(record, dict):
        return None
    return reviews.parse_github_timestamp(record.get("timestamp"))


def _legacy_compare_cross_channel_conversation(contributor: dict | None, reviewer: dict | None) -> int:
    contributor_time = _legacy_record_timestamp(contributor) or datetime.min.replace(tzinfo=timezone.utc)
    reviewer_time = _legacy_record_timestamp(reviewer) or datetime.min.replace(tzinfo=timezone.utc)
    contributor_key = str((contributor or {}).get("semantic_key", ""))
    reviewer_key = str((reviewer or {}).get("semantic_key", ""))
    if (contributor_time, contributor_key) == (reviewer_time, reviewer_key):
        return 0
    if contributor_time > reviewer_time:
        return 1
    if contributor_time < reviewer_time:
        return -1
    if contributor_key >= reviewer_key:
        return 1
    return -1


def _legacy_initial_reviewer_anchor(review_data: dict) -> str | None:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        value = review_data.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _legacy_contributor_revision_handoff_record(review_data: dict, current_head: str | None, reviewer_review: dict | None) -> dict | None:
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    if not isinstance(contributor_revision, dict):
        return None
    revision_head = contributor_revision.get("reviewed_head_sha")
    if not isinstance(revision_head, str) or not isinstance(current_head, str):
        return None
    if revision_head != current_head:
        return None
    reviewer_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if isinstance(reviewer_head, str) and reviewer_head == current_head:
        return None
    return contributor_revision


def test_reviewer_response_derivation_supports_pure_inputs_without_live_reads():
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )

    result = reviewer_response_policy.derive_reviewer_response_state(
        review,
        issue_is_pull_request=True,
        current_head="head-1",
        approval_result={
            "ok": True,
            "completion": {"completed": False},
            "write_approval": {"has_write_approval": False},
        },
    )

    assert result["state"] == "awaiting_contributor_response"
    assert result["reason"] == "completion_missing"
    assert result["reviewer_review"]["semantic_key"] == "pull_request_review:10"


def test_h1a_reviewer_response_scenario_matrix_matches_frozen_outputs(monkeypatch):
    matrix = _load_matrix()

    assert matrix["harness_id"] == "H1a reviewer-response derivation equivalence"

    for scenario in matrix["scenarios"]:
        with monkeypatch.context() as scenario_monkeypatch:
            result = _run_scenario(scenario_monkeypatch, scenario["id"])
        assert result["state"] == scenario["state"], scenario["id"]
        assert result["reason"] == scenario["reason"], scenario["id"]


def test_h1b_reviewer_response_policy_matches_legacy_derivation_for_frozen_matrix(monkeypatch):
    matrix = _load_matrix()

    for scenario in matrix["scenarios"]:
        with monkeypatch.context() as scenario_monkeypatch:
            runtime, review = _build_scenario(scenario_monkeypatch, scenario["id"])
            legacy_result = _legacy_compute_reviewer_response_state(runtime, 42, review)
            policy_result = reviewer_response_policy.compute_reviewer_response_state(runtime, 42, review)
        assert policy_result == legacy_result, scenario["id"]


def test_h1b_reviews_module_delegates_reviewer_response_to_policy_owner():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")
    policy_text = Path("scripts/reviewer_bot_core/reviewer_response_policy.py").read_text(encoding="utf-8")
    helper_text = Path("scripts/reviewer_bot_core/reviewer_review_helpers.py").read_text(encoding="utf-8")

    assert "return reviewer_response_policy.compute_reviewer_response_state(" in reviews_text
    assert "def compute_reviewer_response_state(" in policy_text
    assert "reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(" in policy_text
    assert "reviewer_review_helpers.build_reviewer_review_record_from_live_review(" in policy_text
    assert "reviewer_review_helpers.compare_records(" in policy_text
    assert "legacy_reviews.get_preferred_current_reviewer_review_for_cycle(" not in policy_text
    assert "legacy_reviews.build_reviewer_review_record_from_live_review(" not in policy_text
    assert "legacy_reviews._compare_records(" not in policy_text
    assert "def get_preferred_current_reviewer_review_for_cycle(" in helper_text
    assert "def build_reviewer_review_record_from_live_review(" in helper_text
    assert "def compare_records(" in helper_text
