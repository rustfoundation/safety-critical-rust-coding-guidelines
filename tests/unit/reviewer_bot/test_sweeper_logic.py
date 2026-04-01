from scripts import reviewer_bot
from scripts.reviewer_bot_lib import sweeper
from tests.fixtures.reviewer_bot import make_state


def test_sweeper_creates_keyed_deferred_gaps_for_visible_comments_reviews_and_dismissals(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-25T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 202, "submitted_at": "2026-03-25T11:00:00Z", "state": "APPROVED"},
            {"id": 303, "submitted_at": "2026-03-25T09:00:00Z", "updated_at": "2026-03-25T12:00:00Z", "state": "DISMISSED"},
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "issue_comment:101" in gaps
    assert "pull_request_review:202" in gaps
    assert "pull_request_review_dismissed:303" in gaps
    assert gaps["pull_request_review_dismissed:303"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"


def test_sweeper_creates_keyed_deferred_gap_for_visible_review_comments(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"state": "open", "head": {"sha": "head-1"}}
        if endpoint == "issues/42/comments?per_page=100&page=1":
            return []
        if endpoint == "pulls/42/comments?per_page=100":
            return [{"id": 404, "created_at": "2026-03-25T10:30:00Z", "user": {"login": "dana", "type": "User"}}]
        if endpoint.startswith("actions/workflows/"):
            return {"workflow_runs": []}
        return None

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "pull_request_review_comment:404" in gaps
    assert gaps["pull_request_review_comment:404"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"


def test_sweeper_skips_dismissed_reviews_already_reconciled_by_source_event_key(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-17T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["pull_request_review_dismissed:303"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 303, "submitted_at": "2026-03-17T09:00:00Z", "updated_at": "2026-03-17T12:00:00Z", "state": "DISMISSED"},
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_sweeper_skips_events_already_reconciled_by_source_event_key(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-17T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["issue_comment:101", "pull_request_review:202"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-17T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [{"id": 202, "submitted_at": "2026-03-17T11:00:00Z", "state": "APPROVED"}],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_discover_visible_comment_events_skips_github_actions_and_bot_comments(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: [
            {
                "id": 100,
                "created_at": "2026-03-25T10:00:00Z",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
            {
                "id": 101,
                "created_at": "2026-03-25T11:00:00Z",
                "user": {"login": "alice", "type": "User"},
            },
        ],
    )

    discovered, complete = sweeper._discover_visible_comment_events(reviewer_bot, 42, review)

    assert complete is True
    assert [item["source_event_key"] for item in discovered] == ["issue_comment:101"]


def test_sweeper_visible_review_repair_refreshes_current_reviewer_activity_without_artifact(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    review["deferred_gaps"]["pull_request_review:202"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}}
        if endpoint == "pulls/42"
        else {"workflow_runs": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 202,
                "submitted_at": "2026-03-25T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    assert review["last_reviewer_activity"] == "2026-03-25T11:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None
    assert "pull_request_review:202" not in review["deferred_gaps"]
    assert "pull_request_review:202" in review["reconciled_source_events"]


def test_visible_review_repair_does_not_clear_transition_warning_for_stale_replayed_review(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["last_reviewer_activity"] = "2026-03-25T11:00:00Z"
    review["transition_warning_sent"] = "2026-04-01T12:12:04Z"
    review["transition_notice_sent_at"] = "2026-04-15T12:12:04Z"
    review["deferred_gaps"]["pull_request_review:202"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}}
        if endpoint == "pulls/42"
        else {"workflow_runs": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 202,
                "submitted_at": "2026-03-25T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    assert review["last_reviewer_activity"] == "2026-03-25T11:00:00Z"
    assert review["transition_warning_sent"] == "2026-04-01T12:12:04Z"
    assert review["transition_notice_sent_at"] == "2026-04-15T12:12:04Z"


def test_repair_visible_review_gap_returns_true_for_bookkeeping_only_mutations(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["deferred_gaps"]["pull_request_review:303"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_reviewer_review_from_live_review",
        lambda review_data, live_review, actor=None: False,
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "refresh_reviewer_review_from_live_preferred_review",
        lambda bot, issue_number, review_data, actor=None: (False, None),
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data: (None, None),
    )

    changed = sweeper._repair_visible_review_gap(
        reviewer_bot,
        review,
        42,
        "pull_request_review:303",
        {
            "id": 303,
            "submitted_at": "2026-03-25T11:00:00Z",
            "state": "COMMENTED",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        },
    )

    assert changed is True
    assert "pull_request_review:303" in review["reconciled_source_events"]
    assert "pull_request_review:303" not in review["deferred_gaps"]


def test_observer_run_reason_mapping_and_near_miss_signature():
    signature = {"status": "waiting", "conclusion": None, "name": "approval_pending"}
    assert (
        sweeper.observer_run_reason_from_details(
            {"status": "waiting", "conclusion": None, "name": "approval_pending"},
            signature,
        )
        == "awaiting_observer_approval"
    )
    assert (
        sweeper.observer_run_reason_from_details(
            {"status": "waiting", "conclusion": None, "name": "almost"},
            signature,
        )
        == "observer_state_unknown"
    )


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
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    result = sweeper.correlate_candidate_observer_runs(
        "issue_comment:101",
        source_event_kind="issue_comment:created",
        source_event_created_at="2026-03-17T10:00:00Z",
        pr_number=42,
        workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
        workflow_runs=[
            {
                "id": 1,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:05:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
            {
                "id": 2,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:40:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
        ],
    )
    assert result["candidate_run_ids"] == [1]


def test_stage_b_artifact_correlation_rejects_ambiguous_exact_matches():
    result = sweeper.correlate_run_artifacts_exact(
        {
            10: [{"source_event_key": "issue_comment:101", "source_run_id": 10, "source_run_attempt": 1, "pr_number": 42}],
            11: [{"source_event_key": "issue_comment:101", "source_run_id": 11, "source_run_attempt": 1, "pr_number": 42}],
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
    expired = {
        "artifact_seen_at": "2026-03-10T00:00:00Z",
        "run_created_at": "2026-03-10T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(expired) == "artifact_expired"
    missing = {
        "artifact_inspection_complete": True,
        "run_created_at": "2026-03-17T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(missing) == "artifact_missing"


def test_sweeper_fetches_single_candidate_run_detail_without_exact_artifact_match(monkeypatch):
    run_correlation = {
        "candidate_run_ids": [123],
        "correlated_run": None,
        "correlated_run_found": False,
    }
    monkeypatch.setattr(
        sweeper,
        "_fetch_run_detail",
        lambda bot, run_id: {"id": run_id, "status": "completed", "conclusion": "action_required"},
    )
    detail = sweeper._maybe_fetch_single_candidate_run_detail(
        reviewer_bot,
        run_correlation,
        {"status": "no_exact_artifact_match"},
    )
    assert detail == {"id": 123, "status": "completed", "conclusion": "action_required"}
    assert run_correlation["correlated_run"] == 123
