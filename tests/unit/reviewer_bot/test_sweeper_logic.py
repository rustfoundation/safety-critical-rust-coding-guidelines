import pytest

from scripts.reviewer_bot_lib import review_state, sweeper
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi
from tests.fixtures.reviewer_bot_sweeper_builders import (
    artifact_payload,
    issue_comment_event,
    pull_request_review_event,
    review_comment_event,
    workflow_run,
)


@pytest.fixture
def freeze_sweeper_now(monkeypatch):
    def apply(timestamp: str) -> None:
        monkeypatch.setattr(sweeper, "_now", lambda: sweeper.parse_timestamp(timestamp))

    return apply


def _runtime(monkeypatch):
    return FakeReviewerBotRuntime(monkeypatch)


def test_sweeper_creates_keyed_deferred_gaps_for_visible_comments_reviews_and_dismissals(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-25T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request(
            "GET",
            "issues/42/comments?per_page=100&page=1",
            status_code=200,
            payload=[issue_comment_event(101, created_at="2026-03-25T10:00:00Z")],
        )
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-submitted-observer.yml/runs?event=pull_request_review&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-comment-observer.yml/runs?event=issue_comment&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-dismissed-observer.yml/runs?event=pull_request_review&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request("GET", "pulls/42/comments?per_page=100", status_code=200, payload=[])
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [
        pull_request_review_event(202, submitted_at="2026-03-25T11:00:00Z", state="APPROVED"),
        pull_request_review_event(303, submitted_at="2026-03-25T09:00:00Z", updated_at="2026-03-25T12:00:00Z", state="DISMISSED"),
    ]

    assert sweeper.sweep_deferred_gaps(runtime, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "issue_comment:101" in gaps
    assert "pull_request_review:202" in gaps
    assert "pull_request_review_dismissed:303" in gaps
    assert gaps["pull_request_review_dismissed:303"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"


def test_sweeper_creates_keyed_deferred_gap_for_visible_review_comments(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-25T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "issues/42/comments?per_page=100&page=1", status_code=200, payload=[])
        .add_request(
            "GET",
            "issues/42/comments?per_page=100&page=2",
            status_code=200,
            payload=[],
        )
        .add_request(
            "GET",
            "pulls/42/comments?per_page=100",
            status_code=200,
            payload=[review_comment_event(404, created_at="2026-03-25T10:30:00Z", login="dana")],
        )
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-comment-observer.yml/runs?event=pull_request_review_comment&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: []

    assert sweeper.sweep_deferred_gaps(runtime, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "pull_request_review_comment:404" in gaps
    assert gaps["pull_request_review_comment:404"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"


def test_sweeper_skips_dismissed_reviews_already_reconciled_by_source_event_key(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-17T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["pull_request_review_dismissed:303"]
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "issues/42/comments?per_page=100&page=1", status_code=200, payload=[])
        .add_request("GET", "issues/42/comments?per_page=100&page=2", status_code=200, payload=[])
        .add_request("GET", "pulls/42/comments?per_page=100", status_code=200, payload=[])
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [pull_request_review_event(303, submitted_at="2026-03-17T09:00:00Z", updated_at="2026-03-17T12:00:00Z", state="DISMISSED")]

    assert sweeper.sweep_deferred_gaps(runtime, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_sweeper_skips_events_already_reconciled_by_source_event_key(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-17T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["issue_comment:101", "pull_request_review:202"]
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request(
            "GET",
            "issues/42/comments?per_page=100&page=1",
            status_code=200,
            payload=[issue_comment_event(101, created_at="2026-03-17T10:00:00Z")],
        )
        .add_request("GET", "issues/42/comments?per_page=100&page=2", status_code=200, payload=[])
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-submitted-observer.yml/runs?event=pull_request_review&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request("GET", "pulls/42/comments?per_page=100", status_code=200, payload=[])
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [pull_request_review_event(202, submitted_at="2026-03-17T11:00:00Z", state="APPROVED")]

    assert sweeper.sweep_deferred_gaps(runtime, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_discover_visible_comment_events_skips_github_actions_and_bot_comments(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-25T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/42/comments?per_page=100&page=1",
        status_code=200,
        payload=[
            issue_comment_event(100, created_at="2026-03-25T10:00:00Z", login="github-actions[bot]", user_type="Bot"),
            issue_comment_event(101, created_at="2026-03-25T11:00:00Z", login="alice"),
        ],
    )
    routes.add_request("GET", "issues/42/comments?per_page=100&page=2", status_code=200, payload=[])
    runtime.github.stub(routes)

    discovered, complete = sweeper._discover_visible_comment_events(runtime, 42, review)

    assert complete is True
    assert [item["source_event_key"] for item in discovered] == ["issue_comment:101"]


def test_sweeper_visible_review_repair_refreshes_current_reviewer_activity_without_artifact(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-25T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    review["deferred_gaps"]["pull_request_review:202"] = {"reason": "artifact_missing"}
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-submitted-observer.yml/runs?event=pull_request_review&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request("GET", "issues/42/comments?per_page=100&page=1", status_code=200, payload=[])
        .add_request("GET", "pulls/42/reviews?per_page=100&page=1", status_code=200, payload=[])
        .add_request("GET", "pulls/42/comments?per_page=100", status_code=200, payload=[])
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [pull_request_review_event(202, submitted_at="2026-03-25T11:00:00Z", state="COMMENTED", commit_id="head-1")]

    assert sweeper.sweep_deferred_gaps(runtime, state) is True
    assert review["last_reviewer_activity"] == "2026-03-25T11:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None
    assert "pull_request_review:202" not in review["deferred_gaps"]
    assert "pull_request_review:202" in review["reconciled_source_events"]


def test_visible_review_repair_does_not_clear_transition_warning_for_stale_replayed_review(monkeypatch, freeze_sweeper_now):
    freeze_sweeper_now("2026-03-25T12:30:00Z")
    runtime = _runtime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["last_reviewer_activity"] = "2026-03-25T11:00:00Z"
    review["transition_warning_sent"] = "2026-04-01T12:12:04Z"
    review["transition_notice_sent_at"] = "2026-04-15T12:12:04Z"
    review["deferred_gaps"]["pull_request_review:202"] = {"reason": "artifact_missing"}
    routes = (
        RouteGitHubApi()
        .add_api("GET", "pulls/42", {"state": "open", "head": {"sha": "head-1"}})
        .add_request("GET", "pulls/42", status_code=200, payload={"state": "open", "head": {"sha": "head-1"}})
        .add_request(
            "GET",
            "actions/workflows/.github%2Fworkflows%2Freviewer-bot-pr-review-submitted-observer.yml/runs?event=pull_request_review&per_page=100&page=1",
            status_code=200,
            payload={"workflow_runs": []},
        )
        .add_request("GET", "issues/42/comments?per_page=100&page=1", status_code=200, payload=[])
        .add_request("GET", "pulls/42/reviews?per_page=100&page=1", status_code=200, payload=[])
        .add_request("GET", "pulls/42/comments?per_page=100", status_code=200, payload=[])
    )
    runtime.github.stub(routes)
    runtime.get_pull_request_reviews = lambda issue_number: [pull_request_review_event(202, submitted_at="2026-03-25T11:00:00Z", state="COMMENTED", commit_id="head-1")]

    assert sweeper.sweep_deferred_gaps(runtime, state) is True
    assert review["last_reviewer_activity"] == "2026-03-25T11:00:00Z"
    assert review["transition_warning_sent"] == "2026-04-01T12:12:04Z"
    assert review["transition_notice_sent_at"] == "2026-04-15T12:12:04Z"


def test_repair_visible_review_gap_returns_true_for_bookkeeping_only_mutations(monkeypatch):
    runtime = _runtime(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["deferred_gaps"]["pull_request_review:303"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(sweeper, "accept_reviewer_review_from_live_review", lambda review_data, live_review, actor=None: False)
    monkeypatch.setattr(sweeper, "refresh_reviewer_review_from_live_preferred_review", lambda bot, issue_number, review_data, actor=None: (False, None))
    monkeypatch.setattr(sweeper, "rebuild_pr_approval_state", lambda bot, issue_number, review_data: (None, None))

    changed = sweeper._repair_visible_review_gap(
        runtime,
        review,
        42,
        "pull_request_review:303",
        pull_request_review_event(303, submitted_at="2026-03-25T11:00:00Z", state="COMMENTED", commit_id="head-1"),
    )

    assert changed is True
    assert "pull_request_review:303" in review["reconciled_source_events"]
    assert "pull_request_review:303" not in review["deferred_gaps"]


def test_observer_run_reason_mapping_and_near_miss_signature():
    signature = {"status": "waiting", "conclusion": None, "name": "approval_pending"}
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "approval_pending"}, signature) == "awaiting_observer_approval"
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "almost"}, signature) == "observer_state_unknown"


def test_approval_pending_signature_is_loaded_from_runbook():
    assert sweeper._approval_pending_signature_from_runbook() == {
        "status": "waiting",
        "conclusion": None,
        "name": "approval_pending",
    }


def test_negative_missing_run_requires_full_scan_and_recheck():
    gap = {
        "source_event_created_at": "2026-03-15T00:00:00Z",
        "full_scan_complete": True,
        "later_recheck_complete": True,
        "correlated_run_found": False,
        "approval_pending_evidence_retained": False,
    }
    assert sweeper.can_mark_observer_run_missing(gap) is True
    gap["later_recheck_complete"] = False
    assert sweeper.can_mark_observer_run_missing(gap) is False


def test_stage_a_candidate_run_correlation_is_exact_to_workflow_event_pr_and_window(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.set_config_value("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    result = sweeper.correlate_candidate_observer_runs(
        runtime,
        "issue_comment:101",
        source_event_kind="issue_comment:created",
        source_event_created_at="2026-03-17T10:00:00Z",
        pr_number=42,
        workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
        workflow_runs=[
            workflow_run(1, event="issue_comment", path=".github/workflows/reviewer-bot-pr-comment-observer.yml", created_at="2026-03-17T10:05:00Z"),
            workflow_run(2, event="issue_comment", path=".github/workflows/reviewer-bot-pr-comment-observer.yml", created_at="2026-03-17T10:40:00Z"),
        ],
    )
    assert result["candidate_run_ids"] == [1]


def test_stage_b_artifact_correlation_rejects_ambiguous_exact_matches():
    result = sweeper.correlate_run_artifacts_exact(
        {
            10: [artifact_payload(source_event_key="issue_comment:101", source_run_id=10)],
            11: [artifact_payload(source_event_key="issue_comment:101", source_run_id=11)],
        },
        "issue_comment:101",
        pr_number=42,
    )
    assert result["status"] == "observer_state_unknown"
    assert result["reason"] == "ambiguous_exact_artifact_matches"


def test_evaluate_gap_state_treats_artifact_download_unavailable_as_unknown():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "artifact_scan_outcomes": {10: "download_unavailable"}},
    )
    assert reason == "observer_state_unknown"
    assert diagnostic == "artifact_download_unavailable"


def test_evaluate_gap_state_only_emits_missing_after_negative_inference_contract():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {
            "source_event_created_at": "2026-03-15T00:00:00Z",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run_found": False,
            "approval_pending_evidence_retained": False,
        },
        {
            "status": "no_candidate_runs",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run": None,
        },
        None,
        None,
    )
    assert reason == "observer_run_missing"
    assert diagnostic == "negative_inference_satisfied"


def test_evaluate_gap_state_completed_success_without_exact_artifact_is_artifact_missing():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "reason": "no_exact_source_event_key_match"},
    )
    assert reason == "artifact_missing"
    assert diagnostic == "no_exact_source_event_key_match"


def test_evaluate_gap_state_completed_success_with_expired_artifact_marks_artifact_expired():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "artifact_scan_outcomes": {10: "expired"}},
    )
    assert reason == "artifact_expired"
    assert diagnostic == "prior_visibility_or_retention_proof_required"


def test_artifact_gap_reason_requires_prior_visibility_or_documented_retention():
    expired = {"artifact_seen_at": "2026-03-10T00:00:00Z", "run_created_at": "2026-03-10T00:00:00Z"}
    assert sweeper.classify_artifact_gap_reason(expired) == "artifact_expired"
    missing = {"artifact_inspection_complete": True, "run_created_at": "2026-03-17T00:00:00Z"}
    assert sweeper.classify_artifact_gap_reason(missing) == "artifact_missing"


def test_artifact_gap_reason_uses_passed_retention_days():
    gap = {
        "run_created_at": "2026-03-01T00:00:00Z",
        "retention_window_documented": True,
    }

    assert sweeper.classify_artifact_gap_reason(
        gap,
        now=sweeper.parse_timestamp("2026-03-05T00:00:00Z"),
        retention_days=3,
    ) == "artifact_expired"


def test_sweeper_fetches_single_candidate_run_detail_without_exact_artifact_match(monkeypatch):
    runtime = _runtime(monkeypatch)
    run_correlation = {"candidate_run_ids": [123], "correlated_run": None, "correlated_run_found": False}
    monkeypatch.setattr(sweeper, "_fetch_run_detail", lambda bot, run_id: {"id": run_id, "status": "completed", "conclusion": "action_required"})
    detail = sweeper._maybe_fetch_single_candidate_run_detail(runtime, run_correlation, {"status": "no_exact_artifact_match"})
    assert detail == {"id": 123, "status": "completed", "conclusion": "action_required"}
    assert run_correlation["correlated_run"] == 123
