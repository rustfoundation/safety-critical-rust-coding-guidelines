import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

import yaml


def _load_observer_contract_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/workflow_contracts/observer_payload_contract_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def _load_fixture_payload(relative_path: str) -> dict:
    data = json.loads(Path(relative_path).read_text(encoding="utf-8"))
    return data["payload"]


def test_issue_comment_direct_workflow_exports_issue_state():
    workflow_text = Path(".github/workflows/reviewer-bot-issue-comment-direct.yml").read_text(
        encoding="utf-8"
    )
    assert "ISSUE_STATE: ${{ github.event.issue.state }}" in workflow_text

def test_pr_comment_observer_workflow_builds_payload_inline_without_bot_src_root():
    workflow = Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8")
    assert "BOT_SRC_ROOT" not in workflow
    assert "build_pr_comment_observer_payload" not in workflow
    assert "Fetch trusted bot source tarball" not in workflow

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
    data = yaml.safe_load(
        Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(encoding="utf-8")
    )
    on_block = data.get("on", data.get(True))
    assert on_block["pull_request_review_comment"]["types"] == ["created"]
    job = data["jobs"]["observer"]
    assert job["permissions"]["contents"] == "read"
    steps = job["steps"]
    assert steps[0]["name"] == "Build deferred review comment artifact"
    assert steps[1]["name"] == "Upload deferred review comment artifact"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(
        encoding="utf-8"
    )
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

def test_workflow_summaries_and_runbook_references_exist():
    runbook = Path("docs/reviewer-bot-review-freshness-operator-runbook.md")
    assert runbook.exists()
    reconcile = Path(".github/workflows/reviewer-bot-reconcile.yml").read_text(encoding="utf-8")
    assert "docs/reviewer-bot-review-freshness-operator-runbook.md" in reconcile


@pytest.mark.parametrize(
    ("fixture_id", "workflow_name", "workflow_file", "artifact_name_shape"),
    [
        (
            "workflow_pr_comment_deferred",
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
        ),
        (
            "workflow_pr_review_submitted_deferred",
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
        ),
        (
            "workflow_pr_review_dismissed_deferred",
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
        ),
        (
            "workflow_pr_review_comment_deferred",
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
        ),
    ],
)
def test_observer_workflow_fixture_identities_match_exact_workflow_contract_strings(
    fixture_id, workflow_name, workflow_file, artifact_name_shape
):
    matrix = _load_observer_contract_matrix()
    fixture_entry = next(
        item for item in matrix["workflow_emitted_payloads"] if item["fixture_id"] == fixture_id
    )
    payload = _load_fixture_payload(fixture_entry["fixture_path"])
    workflow_text = Path(workflow_file).read_text(encoding="utf-8")
    workflow_data = yaml.safe_load(workflow_text)

    assert fixture_entry["contract_source"] == "workflow YAML"
    assert fixture_entry["source_workflow_file"] == workflow_file
    assert payload["source_workflow_name"] == workflow_name
    assert payload["source_workflow_file"] == workflow_file
    assert workflow_data["name"] == workflow_name
    assert artifact_name_shape in workflow_text

def test_build_pr_comment_observer_payload_marks_trusted_direct_same_repo_as_observer_noop(monkeypatch):
    from scripts.reviewer_bot_lib import comment_routing
    from tests.fixtures.comment_routing_harness import CommentRoutingHarness

    harness = CommentRoutingHarness(monkeypatch)
    harness.config.set("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    harness.config.set("COMMENT_USER_TYPE", "User")
    harness.config.set("COMMENT_AUTHOR", "PLeVasseur")
    harness.config.set("COMMENT_AUTHOR_ASSOCIATION", "COLLABORATOR")
    harness.config.set("COMMENT_SENDER_TYPE", "User")
    harness.config.set("COMMENT_INSTALLATION_ID", "")
    harness.config.set("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    harness.config.set("COMMENT_BODY", "@guidelines-bot /r? @felix91gr")
    harness.config.set("COMMENT_ID", "100")
    harness.config.set("COMMENT_AUTHOR_ID", "123")
    harness.config.set("COMMENT_CREATED_AT", "2026-03-20T20:48:25Z")
    harness.config.set("GITHUB_RUN_ID", "999")
    harness.config.set("GITHUB_RUN_ATTEMPT", "1")
    harness.github.add_api(
        "GET",
        "pulls/42",
        {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "PLeVasseur"},
        },
    )

    payload = comment_routing.build_pr_comment_observer_payload(harness.runtime, 42)

    assert payload["kind"] == "observer_noop"
    assert payload["reason"] == "trusted_direct_same_repo_human_comment"
    assert payload["source_event_key"] == "issue_comment:100"
