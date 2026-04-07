from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import (
    reconcile,
    reconcile_payloads,
    reconcile_reads,
    review_state,
)
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reconcile_harness import review_comment_payload
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_review_comment_artifact_identity_validation(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.stub_deferred_payload(
        review_comment_payload(
            pr_number=42,
            comment_id=304,
            source_event_key="pull_request_review_comment:304",
            body="review comment body",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=704,
            source_run_attempt=1,
        )
    )
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_ID", "704")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    routes = (
        RouteGitHubApi()
        .add_request("GET", "pulls/42", status_code=200, payload={"user": {"login": "dana"}, "labels": []})
        .add_request(
            "GET",
            "pulls/comments/304",
            status_code=200,
            payload={
                "body": "review comment body",
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
                "created_at": "2026-03-17T10:00:00Z",
            },
        )
    )
    runtime.github.stub(routes)

    assert reconcile.handle_workflow_run_event(runtime, state) is True


def test_validate_workflow_run_artifact_identity_accepts_matching_contract():
    bot = SimpleNamespace(
        get_config_value=lambda name, default="": {
            "WORKFLOW_RUN_TRIGGERING_NAME": "Reviewer Bot PR Comment Observer",
            "WORKFLOW_RUN_TRIGGERING_ID": "610",
            "WORKFLOW_RUN_TRIGGERING_ATTEMPT": "1",
            "WORKFLOW_RUN_TRIGGERING_CONCLUSION": "success",
        }.get(name, default),
    )
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
    }

    reconcile_payloads.validate_workflow_run_artifact_identity(bot, payload)


def test_read_reconcile_object_fails_closed_for_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        result=github_result(502, {"message": "bad gateway"}, retry_attempts=1),
    )
    runtime.github.stub(routes)

    with pytest.raises(reconcile_reads.ReconcileReadError, match="pull request #42 unavailable") as exc_info:
        reconcile_reads.read_reconcile_object(runtime, "pulls/42", label="pull request #42")

    assert exc_info.value.failure_kind == "server_error"


def test_read_optional_reconcile_object_returns_none_for_not_found(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
        status_code=404,
        payload={"message": "missing"},
        headers={},
        text="missing",
        ok=False,
        failure_kind="not_found",
        retry_attempts=0,
        transport_error=None,
    )

    assert reconcile_reads.read_optional_reconcile_object(runtime, "pulls/42/reviews/11", label="live review #11") is None


def test_read_live_pr_replay_context_normalizes_author_and_labels(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    routes = RouteGitHubApi().add_request(
        "GET",
        "pulls/42",
        status_code=200,
        payload={"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}, {"name": "fls-audit"}]},
    )
    runtime.github.stub(routes)

    context = reconcile_reads.read_live_pr_replay_context(runtime, 42)

    assert context == reconcile_reads.LivePrReplayContext(
        issue_author="dana",
        issue_labels=("coding guideline", "fls-audit"),
    )


def test_read_live_comment_replay_context_normalizes_comment_metadata():
    context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
            "author_association": "MEMBER",
            "performed_via_github_app": None,
        },
        {"actor_login": "alice"},
    )

    assert context == reconcile_reads.LiveCommentReplayContext(
        comment_author="alice",
        comment_user_type="User",
        comment_author_association="MEMBER",
        comment_sender_type="User",
        comment_installation_id="",
        comment_performed_via_github_app=False,
    )
