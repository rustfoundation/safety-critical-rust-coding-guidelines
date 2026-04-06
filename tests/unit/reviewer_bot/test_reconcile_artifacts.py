from pathlib import Path

from scripts.reviewer_bot_lib import reconcile, review_state
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reconcile_harness import review_comment_payload
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi


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


def test_reconcile_payloads_and_reads_remain_normalized_inputs_for_replay_policy():
    payloads_text = Path("scripts/reviewer_bot_lib/reconcile_payloads.py").read_text(encoding="utf-8")
    reads_text = Path("scripts/reviewer_bot_lib/reconcile_reads.py").read_text(encoding="utf-8")
    policy_text = Path("scripts/reviewer_bot_core/reconcile_replay_policy.py").read_text(encoding="utf-8")

    assert "def parse_deferred_context_payload(" in payloads_text
    assert "def read_reconcile_object(" in reads_text
    assert "github_api_request" not in policy_text
    assert "source_workflow_file" not in policy_text
