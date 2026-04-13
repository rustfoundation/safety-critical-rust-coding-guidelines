from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.reviewer_bot_lib.config import LeaseContext

CLEAR_REVIEWER_BOT_ENV_VARS = {
    "ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE",
    "COMMENT_AUTHOR",
    "COMMENT_BODY",
    "COMMENT_ID",
    "COMMENT_SOURCE_EVENT_KEY",
    "EVENT_ACTION",
    "EVENT_NAME",
    "GITHUB_EVENT_PATH",
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
    return LeaseContext(
        lock_token="test-lock-token",
        lock_owner_run_id="test-run",
        lock_owner_workflow="test-workflow",
        lock_owner_job="test-job",
        state_issue_url="https://example.com/state",
    )


def clear_reviewer_bot_env(monkeypatch) -> None:
    for name in CLEAR_REVIEWER_BOT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def set_env_values(config, **values) -> None:
    for name, value in values.items():
        config.set(name, value)


def set_process_env_values(monkeypatch, **values) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))


def set_workflow_run_event_payload(config, workflow_name: str) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump({"workflow_run": {"name": workflow_name}}, handle)
        path = Path(handle.name)
    config.set("GITHUB_EVENT_PATH", str(path))
    return str(path)
