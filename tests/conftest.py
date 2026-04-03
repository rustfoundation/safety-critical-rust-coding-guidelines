import pytest

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.config import AssignmentAttempt, GitHubApiResult
from tests.fixtures.reviewer_bot_env import (
    build_test_lease_context,
    reset_reviewer_bot_process_state,
)
from tests.fixtures.reviewer_bot_recorders import (
    record_comment_dicts,
    record_status_label_ops,
)


@pytest.fixture(autouse=True)
def reset_reviewer_bot_process_state_fixture():
    with pytest.MonkeyPatch().context() as monkeypatch:
        reset_reviewer_bot_process_state(monkeypatch, reviewer_bot)
        yield


@pytest.fixture
def setenv_many(monkeypatch):
    def setter(values: dict[str, str]):
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return setter


@pytest.fixture
def lease_context():
    return build_test_lease_context()


@pytest.fixture
def tmp_deferred_path(tmp_path):
    return tmp_path / "deferred-context.json"


@pytest.fixture
def stub_api(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: GitHubApiResult(
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
        lambda *args, **kwargs: AssignmentAttempt(success=True, status_code=201),
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
    return record_comment_dicts(reviewer_bot)


@pytest.fixture
def captured_status_label_ops(monkeypatch):
    return record_status_label_ops(reviewer_bot)
