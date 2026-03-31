from pathlib import Path

import yaml


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
