import pytest

from scripts import reviewer_bot


@pytest.fixture(autouse=True)
def clear_env():
    env_vars = {
        "COMMENT_BODY",
        "COMMENT_AUTHOR",
        "COMMENT_ID",
        "ALLOW_EMPTY_ACTIVE_REVIEWS_WRITE",
        "EVENT_ACTION",
        "EVENT_NAME",
        "ISSUE_NUMBER",
        "ISSUE_AUTHOR",
        "IS_PULL_REQUEST",
        "ISSUE_LABELS",
        "LABEL_NAME",
        "MANUAL_ACTION",
        "PR_IS_CROSS_REPOSITORY",
        "REVIEW_AUTHOR",
        "REVIEW_STATE",
        "REPO_OWNER",
        "REPO_NAME",
        "WORKFLOW_RUN_EVENT",
        "WORKFLOW_RUN_EVENT_ACTION",
        "WORKFLOW_RUN_HEAD_SHA",
        "WORKFLOW_RUN_RECONCILE_PR_NUMBER",
        "WORKFLOW_RUN_RECONCILE_HEAD_SHA",
        "WORKFLOW_RUN_ID",
        "WORKFLOW_NAME",
        "WORKFLOW_JOB_NAME",
    }
    with pytest.MonkeyPatch().context() as monkeypatch:
        for name in env_vars:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(
            reviewer_bot,
            "ACTIVE_LEASE_CONTEXT",
            reviewer_bot.LeaseContext(
                lock_token="test-lock-token",
                lock_owner_run_id="test-run",
                lock_owner_workflow="test-workflow",
                lock_owner_job="test-job",
                state_issue_url="https://example.com/state",
            ),
        )
        monkeypatch.setattr(reviewer_bot, "TOUCHED_ISSUE_NUMBERS", set())
        yield


@pytest.fixture
def stub_api(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={},
            headers={},
            text="",
            ok=True,
        ),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "assign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        reviewer_bot,
        "request_reviewer_assignment",
        lambda *args, **kwargs: reviewer_bot.AssignmentAttempt(success=True, status_code=201),
    )
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_pr_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_assignee", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda *args, **kwargs: {"a", "b"})
    monkeypatch.setattr(reviewer_bot, "add_label", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "add_label_with_status", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_label", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_label_with_status", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "ensure_label_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "fetch_members", lambda *args, **kwargs: [])


@pytest.fixture
def captured_comments(monkeypatch):
    comments = []

    def record_comment(issue_number, body):
        comments.append({"issue_number": issue_number, "body": body})
        return True

    monkeypatch.setattr(reviewer_bot, "post_comment", record_comment)
    return comments


@pytest.fixture
def captured_status_label_ops(monkeypatch):
    operations = []

    def record_add(issue_number, label):
        operations.append(("add", issue_number, label))
        return True

    def record_remove(issue_number, label):
        operations.append(("remove", issue_number, label))
        return True

    monkeypatch.setattr(reviewer_bot, "add_label_with_status", record_add)
    monkeypatch.setattr(reviewer_bot, "remove_label_with_status", record_remove)
    monkeypatch.setattr(reviewer_bot, "ensure_label_exists", lambda *args, **kwargs: True)
    return operations
