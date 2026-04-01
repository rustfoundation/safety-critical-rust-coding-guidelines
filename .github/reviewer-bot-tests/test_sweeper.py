import os
from pathlib import Path

import pytest
import yaml
from factories import make_state, make_zip_payload
from fakes import FakeGitHubResponse

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import sweeper


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
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "approval_pending"}, signature) == "awaiting_observer_approval"
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "almost"}, signature) == "observer_state_unknown"

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

def test_stage_a_candidate_run_correlation_is_exact_to_workflow_event_pr_and_window():
    os.environ["GITHUB_REPOSITORY"] = "rustfoundation/safety-critical-rust-coding-guidelines"
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

def test_list_run_artifacts_consumes_retry_aware_success(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"artifacts": [{"id": 1, "name": "artifact"}]},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        ),
    )

    assert sweeper._list_run_artifacts(reviewer_bot, 10) == [{"id": 1, "name": "artifact"}]

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
    monkeypatch.setattr(sweeper, "_fetch_run_detail", lambda bot, run_id: {"id": run_id, "status": "completed", "conclusion": "action_required"})
    detail = sweeper._maybe_fetch_single_candidate_run_detail(reviewer_bot, run_correlation, {"status": "no_exact_artifact_match"})
    assert detail == {"id": 123, "status": "completed", "conclusion": "action_required"}
    assert run_correlation["correlated_run"] == 123

def test_workflow_policy_split_and_lock_only_boundaries():
    workflows_dir = Path(".github/workflows")
    required = {
        "reviewer-bot-issues.yml",
        "reviewer-bot-issue-comment-direct.yml",
        "reviewer-bot-sweeper-repair.yml",
        "reviewer-bot-pr-metadata.yml",
        "reviewer-bot-pr-comment-trusted.yml",
        "reviewer-bot-pr-comment-observer.yml",
        "reviewer-bot-pr-review-submitted-observer.yml",
        "reviewer-bot-pr-review-dismissed-observer.yml",
        "reviewer-bot-pr-review-comment-observer.yml",
        "reviewer-bot-reconcile.yml",
        "reviewer-bot-privileged-commands.yml",
    }
    assert required.issubset({path.name for path in workflows_dir.glob("reviewer-bot-*.yml")})
    for path in required:
        data = yaml.safe_load((workflows_dir / path).read_text(encoding="utf-8"))
        jobs = data.get("jobs", {})
        for job in jobs.values():
            permissions = job.get("permissions", {})
            steps = job.get("steps", [])
            uses_values = [step.get("uses", "") for step in steps if isinstance(step, dict)]
            text = (workflows_dir / path).read_text(encoding="utf-8")
            if "observer" in path:
                assert permissions.get("contents") == "read"
                assert all("checkout" not in value for value in uses_values)
            if permissions.get("contents") == "write" and path != "reviewer-bot-privileged-commands.yml":
                assert all("checkout" not in value for value in uses_values)
                assert "Temporary lock debt" in text
            for value in uses_values:
                if value:
                    assert "@" in value and len(value.split("@", 1)[1]) == 40

def test_pr_comment_observer_workflow_builds_payload_inline_without_bot_src_root():
    workflow = Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8")
    assert "BOT_SRC_ROOT" not in workflow
    assert "build_pr_comment_observer_payload" not in workflow
    assert "Fetch trusted bot source tarball" not in workflow

def test_workflow_summaries_and_runbook_references_exist():
    runbook = Path("docs/reviewer-bot-review-freshness-operator-runbook.md")
    assert runbook.exists()
    reconcile = Path(".github/workflows/reviewer-bot-reconcile.yml").read_text(encoding="utf-8")
    assert "docs/reviewer-bot-review-freshness-operator-runbook.md" in reconcile

def test_trusted_pr_comment_workflow_preflights_same_repo_before_mutation():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8"))
    job = data["jobs"]["reviewer-bot-pr-comment-trusted"]
    steps = job["steps"]
    assert steps[0]["name"] == "Decide whether same-repo trusted path applies"
    assert steps[1]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[2]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[3]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[4]["name"] == "Trusted path skipped"
    assert steps[4]["if"] == "env.RUN_TRUSTED_PR_COMMENT != 'true'"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8")
    assert "https://api.github.com/repos/{repo}/pulls/{pr_number}" in workflow_text
    assert "RUN_TRUSTED_PR_COMMENT" in workflow_text

def test_pr_comment_observer_workflow_uses_inline_payload_builder():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8"))
    job = data["jobs"]["observer"]
    steps = job["steps"]
    assert steps[0]["name"] == "Build deferred comment artifact"
    assert steps[1]["name"] == "Upload deferred comment artifact"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8")
    assert "build_pr_comment_observer_payload" not in workflow_text
    assert 'uv run --project "$BOT_SRC_ROOT"' not in workflow_text

def test_review_comment_observer_workflow_exists_and_is_read_only():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    assert on_block["pull_request_review_comment"]["types"] == ["created"]
    job = data["jobs"]["observer"]
    assert job["permissions"]["contents"] == "read"
    steps = job["steps"]
    assert steps[0]["name"] == "Build deferred review comment artifact"
    assert steps[1]["name"] == "Upload deferred review comment artifact"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(encoding="utf-8")
    assert "checkout" not in workflow_text
    assert "pull_request_review_comment" in workflow_text

def test_mutating_reviewer_bot_workflows_do_not_share_global_github_concurrency():
    workflow_paths = [
        ".github/workflows/reviewer-bot-issues.yml",
        ".github/workflows/reviewer-bot-issue-comment-direct.yml",
        ".github/workflows/reviewer-bot-sweeper-repair.yml",
        ".github/workflows/reviewer-bot-pr-metadata.yml",
        ".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        ".github/workflows/reviewer-bot-reconcile.yml",
        ".github/workflows/reviewer-bot-privileged-commands.yml",
    ]
    for workflow_path in workflow_paths:
        data = yaml.safe_load(Path(workflow_path).read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            assert "concurrency" not in job

def test_download_artifact_payload_retries_429_then_succeeds(monkeypatch):
    payload = {"source_event_key": "issue_comment:100"}
    responses = iter(
        [
            FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
        ]
    )
    success_response = FakeGitHubResponse(200, None, "")
    success_response.content = make_zip_payload("deferred-comment.json", payload)

    def fake_request(*args, **kwargs):
        response = next(responses, success_response)
        return response

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sweeper.requests, "request", fake_request)
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, artifact_payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "ok"
    assert artifact_payload == payload

def test_download_artifact_payload_reports_request_exception_unavailable(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sweeper.requests.RequestException("timeout")
        ),
    )
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None

def test_download_artifact_payload_reports_retry_exhaustion_unavailable(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
    )
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None

def test_list_run_artifacts_returns_none_when_api_payload_unavailable(monkeypatch):
    monkeypatch.setattr(sweeper, "_read_api_payload", lambda bot, endpoint: (None, "server_error"))

    assert sweeper._list_run_artifacts(reviewer_bot, 42) is None


@pytest.mark.parametrize(
    ("workflow_path", "artifact_name", "payload_name"),
    [
        (
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-comment.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-submitted.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-dismissed.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-comment.json",
        ),
    ],
)
def test_observer_workflow_files_match_expected_artifact_contract(
    workflow_path, artifact_name, payload_name
):
    workflow_text = Path(workflow_path).read_text(encoding="utf-8")

    assert artifact_name in workflow_text
    assert payload_name in workflow_text
