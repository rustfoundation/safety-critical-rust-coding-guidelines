import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import (
    event_inputs,
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


def _load_fixture_payload(relative_path: str) -> dict:
    return json.loads(Path(relative_path).read_text(encoding="utf-8"))["payload"]


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

    runtime.ACTIVE_LEASE_CONTEXT = object()

    assert reconcile.handle_workflow_run_event_result(runtime, state).state_changed is True


def test_validate_workflow_run_artifact_identity_accepts_matching_contract():
    bot = SimpleNamespace(
        get_config_value=lambda name, default="": {
            "WORKFLOW_RUN_TRIGGERING_NAME": "Reviewer Bot PR Comment Router",
            "WORKFLOW_RUN_TRIGGERING_ID": "610",
            "WORKFLOW_RUN_TRIGGERING_ATTEMPT": "1",
            "WORKFLOW_RUN_TRIGGERING_CONCLUSION": "success",
        }.get(name, default),
    )
    payload = {
        "payload_kind": "deferred_comment",
        "schema_version": 3,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Router",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
    }

    reconcile_payloads.validate_workflow_run_artifact_identity(bot, payload)


@pytest.mark.parametrize(
    "fixture_path",
    [
        "tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json",
        "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
        "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
        "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
    ],
)
def test_deferred_payload_parsing_does_not_require_artifact_name_helpers(fixture_path):
    payload = _load_fixture_payload(fixture_path)
    payload.pop("source_artifact_name", None)

    parsed = reconcile_payloads.parse_deferred_context_payload(payload)

    assert parsed.identity.source_run_id == payload["source_run_id"]
    assert parsed.identity.source_run_attempt == payload["source_run_attempt"]
    assert parsed.identity.source_event_key == payload["source_event_key"]
    if payload["payload_kind"] == "deferred_review_comment":
        assert parsed.source_commit_id == payload["source_commit_id"]


def test_review_request_events_are_classified_as_no_retained_trigger():
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path(".github/workflows").glob("reviewer-bot-*.yml")
    )
    classification = {
        "review_requested": "classified_no_retained_trigger",
        "review_request_removed": "classified_no_retained_trigger",
    }

    assert classification == {
        "review_requested": "classified_no_retained_trigger",
        "review_request_removed": "classified_no_retained_trigger",
    }
    assert "review_requested" not in workflow_text
    assert "review_request_removed" not in workflow_text


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
        comment_sender_type=None,
        comment_installation_id=None,
        comment_performed_via_github_app=False,
        comment_performed_via_github_app_available=True,
    )


def test_read_live_comment_replay_context_uses_only_exact_live_provenance_fields():
    context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "sender": {"type": "Bot"},
            "installation": {"id": 12345},
            "performed_via_github_app": {"id": 67890},
        },
        {"actor_login": "alice"},
    )

    assert context == reconcile_reads.LiveCommentReplayContext(
        comment_author="github-actions[bot]",
        comment_user_type="Bot",
        comment_sender_type="Bot",
        comment_installation_id="12345",
        comment_performed_via_github_app=True,
        comment_sender_type_available=True,
        comment_installation_id_available=True,
        comment_performed_via_github_app_available=True,
    )


def test_read_live_comment_replay_context_distinguishes_absent_from_explicit_false_app():
    absent_context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
        },
        {"actor_login": "alice"},
    )
    false_context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
            "performed_via_github_app": None,
        },
        {"actor_login": "alice"},
    )

    assert absent_context.comment_performed_via_github_app is None
    assert absent_context.comment_performed_via_github_app_available is False
    assert false_context.comment_performed_via_github_app is False
    assert false_context.comment_performed_via_github_app_available is True


def test_replay_comment_request_preserves_payload_app_truth_for_non_exact_live_shape():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload["comment_performed_via_github_app"] = True
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
            "performed_via_github_app": "false",
        },
        {"actor_login": "alice"},
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert live_context.comment_performed_via_github_app is None
    assert live_context.comment_performed_via_github_app_available is False
    assert request.comment_performed_via_github_app is True


@pytest.mark.parametrize("installation", [None, {}, {"id": ""}, {"id": "bad"}, {"id": 0}])
def test_replay_comment_request_preserves_payload_installation_for_non_exact_live_shape(installation):
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload["comment_installation_id"] = "12345"
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
            "installation": installation,
        },
        {"actor_login": "alice"},
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert live_context.comment_installation_id is None
    assert live_context.comment_installation_id_available is False
    assert request.comment_installation_id == "12345"


@pytest.mark.parametrize("performed_via_app", [{}, {"id": ""}, {"id": "bad"}])
def test_replay_comment_request_preserves_payload_app_truth_for_malformed_live_app_dict(performed_via_app):
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload["comment_performed_via_github_app"] = True
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.read_live_comment_replay_context(
        {
            "user": {"login": "alice", "type": "User"},
            "performed_via_github_app": performed_via_app,
        },
        {"actor_login": "alice"},
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert live_context.comment_performed_via_github_app is None
    assert live_context.comment_performed_via_github_app_available is False
    assert request.comment_performed_via_github_app is True


def test_replay_comment_request_preserves_payload_provenance_without_exact_live_fields():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload.update(
        {
            "comment_sender_type": "User",
            "comment_installation_id": "12345",
            "comment_performed_via_github_app": True,
        }
    )
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.LiveCommentReplayContext(
        comment_author="alice",
        comment_user_type="User",
        comment_sender_type=None,
        comment_installation_id=None,
        comment_performed_via_github_app=None,
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert request.comment_sender_type == "User"
    assert request.comment_installation_id == "12345"
    assert request.comment_performed_via_github_app is True


def test_replay_comment_request_accepts_exact_live_provenance_over_payload():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.LiveCommentReplayContext(
        comment_author="github-actions[bot]",
        comment_user_type="Bot",
        comment_sender_type="Bot",
        comment_installation_id="12345",
        comment_performed_via_github_app=True,
        comment_sender_type_available=True,
        comment_installation_id_available=True,
        comment_performed_via_github_app_available=True,
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert request.comment_author == "github-actions[bot]"
    assert request.comment_user_type == "Bot"
    assert request.comment_sender_type == "Bot"
    assert request.comment_installation_id == "12345"
    assert request.comment_performed_via_github_app is True


def test_replay_comment_request_accepts_exact_live_false_performed_via_app():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload["comment_performed_via_github_app"] = True
    parsed_payload = reconcile_payloads.parse_deferred_context_payload(payload)
    live_context = reconcile_reads.LiveCommentReplayContext(
        comment_author="alice",
        comment_user_type="User",
        comment_sender_type=None,
        comment_installation_id=None,
        comment_performed_via_github_app=False,
        comment_performed_via_github_app_available=True,
    )

    request = event_inputs.build_replay_comment_event_request(parsed_payload, live_comment=live_context)

    assert request.comment_performed_via_github_app is False
