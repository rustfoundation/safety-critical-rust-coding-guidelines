from __future__ import annotations

from scripts import reviewer_bot

CLEAR_REVIEWER_BOT_ENV_VARS = {
    "ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE",
    "COMMENT_AUTHOR",
    "COMMENT_BODY",
    "COMMENT_ID",
    "COMMENT_SOURCE_EVENT_KEY",
    "EVENT_ACTION",
    "EVENT_NAME",
    "IS_PULL_REQUEST",
    "ISSUE_AUTHOR",
    "ISSUE_LABELS",
    "ISSUE_NUMBER",
    "LABEL_NAME",
    "MANUAL_ACTION",
    "PR_IS_CROSS_REPOSITORY",
    "REPO_NAME",
    "REPO_OWNER",
    "REVIEW_AUTHOR",
    "REVIEW_STATE",
    "WORKFLOW_JOB_NAME",
    "WORKFLOW_NAME",
    "WORKFLOW_RUN_EVENT",
    "WORKFLOW_RUN_EVENT_ACTION",
    "WORKFLOW_RUN_HEAD_SHA",
    "WORKFLOW_RUN_ID",
    "WORKFLOW_RUN_RECONCILE_HEAD_SHA",
    "WORKFLOW_RUN_RECONCILE_PR_NUMBER",
}


def build_test_lease_context():
    return reviewer_bot.LeaseContext(
        lock_token="test-lock-token",
        lock_owner_run_id="test-run",
        lock_owner_workflow="test-workflow",
        lock_owner_job="test-job",
        state_issue_url="https://example.com/state",
    )


def reset_reviewer_bot_process_state(monkeypatch) -> None:
    for name in CLEAR_REVIEWER_BOT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", build_test_lease_context())
    monkeypatch.setattr(reviewer_bot, "TOUCHED_ISSUE_NUMBERS", set())
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)


def set_env_values(config, **values) -> None:
    for name, value in values.items():
        config.set(name, value)
