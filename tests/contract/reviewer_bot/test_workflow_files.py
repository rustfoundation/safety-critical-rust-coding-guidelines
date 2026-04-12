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

def test_pr_comment_router_workflow_builds_payload_inline_without_bot_src_root():
    workflow = Path(".github/workflows/reviewer-bot-pr-comment-router.yml").read_text(encoding="utf-8")
    assert "build_pr_comment_observer_payload" not in workflow
    assert "Fetch trusted bot source tarball" in workflow

def test_pr_comment_router_workflow_contains_route_and_trusted_jobs_in_order():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-router.yml").read_text(encoding="utf-8"))
    assert set(data["jobs"]) == {"route-pr-comment", "trusted-direct"}
    route_steps = data["jobs"]["route-pr-comment"]["steps"]
    trusted_steps = data["jobs"]["trusted-direct"]["steps"]
    assert route_steps[0]["name"] == "Route PR comment"
    assert route_steps[1]["name"] == "Upload deferred comment artifact"
    assert trusted_steps[0]["name"] == "Install uv"
    assert trusted_steps[1]["name"] == "Fetch trusted bot source tarball"
    assert trusted_steps[2]["name"] == "Run reviewer bot"

def test_pr_comment_router_upload_is_emitted_only_for_deferred_reconcile():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-router.yml").read_text(encoding="utf-8"))
    upload_step = data["jobs"]["route-pr-comment"]["steps"][1]
    assert upload_step["if"] == "${{ steps.route.outputs.route_outcome == 'deferred_reconcile' }}"

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
        ".github/workflows/reviewer-bot-pr-comment-router.yml",
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
        "reviewer-bot-pr-comment-router.yml",
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
            if permissions.get("contents") == "write" and path not in {
                "reviewer-bot-privileged-commands.yml",
                "reviewer-bot-pr-comment-router.yml",
            }:
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
    ("fixture_path", "workflow_file", "payload_kind", "expected_event_name", "expected_event_action"),
    [
        (
            "tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json",
            ".github/workflows/reviewer-bot-pr-comment-router.yml",
            "deferred_comment",
            "issue_comment",
            "created",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "deferred_review_submitted",
            "pull_request_review",
            "submitted",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "deferred_review_dismissed",
            "pull_request_review",
            "dismissed",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "deferred_review_comment",
            "pull_request_review_comment",
            "created",
        ),
    ],
)
def test_observer_workflow_fixtures_match_trigger_event_shape(
    fixture_path, workflow_file, payload_kind, expected_event_name, expected_event_action
):
    matrix = _load_observer_contract_matrix()
    fixture_entry = next(
        item for item in matrix["payload_contracts"] if item["payload_kind"] == payload_kind
    )
    payload = _load_fixture_payload(fixture_path)
    workflow_text = Path(workflow_file).read_text(encoding="utf-8")
    workflow_data = yaml.safe_load(workflow_text)
    on_block = workflow_data.get("on", workflow_data.get(True))

    assert fixture_entry["owner"] == workflow_file
    assert fixture_entry["payload_kind"] == payload_kind
    assert payload["source_event_name"] == expected_event_name
    assert payload["source_event_action"] == expected_event_action
    assert expected_event_name in on_block
