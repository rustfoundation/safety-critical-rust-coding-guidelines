import pytest

from scripts.reviewer_bot_lib import commands, reconcile, review_state
from scripts.reviewer_bot_lib.config import GitHubApiResult
from scripts.reviewer_bot_lib import lifecycle
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_parse_deferred_context_payload_returns_typed_review_payload():
    payload = {
        "schema_version": 2,
        "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        "source_run_id": 500,
        "source_run_attempt": 2,
        "source_event_name": "pull_request_review",
        "source_event_action": "submitted",
        "source_event_key": "pull_request_review:11",
        "pr_number": 42,
        "review_id": 11,
        "source_submitted_at": "2026-03-17T10:00:00Z",
        "source_review_state": "COMMENTED",
        "source_commit_id": "head-1",
        "actor_login": "alice",
    }

    parsed = reconcile.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reconcile.DeferredReviewPayload)
    assert parsed.identity.source_event_name == "pull_request_review"
    assert parsed.review_id == 11
    assert parsed.pr_number == 42


def test_parse_deferred_context_payload_returns_typed_comment_payload():
    payload = {
        "schema_version": 2,
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": "issue_comment:210",
        "pr_number": 42,
        "comment_id": 210,
        "comment_class": "command_only",
        "has_non_command_text": False,
        "source_body_digest": "abc123",
        "source_created_at": "2026-03-17T10:00:00Z",
        "actor_login": "bob",
    }

    parsed = reconcile.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reconcile.DeferredCommentPayload)
    assert parsed.identity.source_event_key == "issue_comment:210"
    assert parsed.comment_id == 210


def test_build_deferred_comment_replay_context_returns_typed_context():
    payload = reconcile.DeferredCommentPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Comment Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
            source_run_id=610,
            source_run_attempt=1,
            source_event_name="issue_comment",
            source_event_action="created",
            source_event_key="issue_comment:210",
        ),
        pr_number=42,
        comment_id=210,
        comment_class="command_plus_text",
        has_non_command_text=True,
        source_body_digest="abc123",
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="bob",
        raw_payload={"source_event_key": "issue_comment:210"},
    )

    context = reconcile.build_deferred_comment_replay_context(
        payload,
        expected_event_name="issue_comment",
        live_comment_endpoint="issues/comments/210",
    )

    assert isinstance(context, reconcile.DeferredCommentReplayContext)
    assert context.comment_id == 210
    assert context.pr_number == 42
    assert context.source_freshness_eligible is True


def test_build_deferred_comment_replay_context_rejects_mismatched_source_event_key():
    payload = reconcile.DeferredCommentPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Comment Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
            source_run_id=610,
            source_run_attempt=1,
            source_event_name="issue_comment",
            source_event_action="created",
            source_event_key="issue_comment:999",
        ),
        pr_number=42,
        comment_id=210,
        comment_class="command_only",
        has_non_command_text=False,
        source_body_digest="abc123",
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="bob",
        raw_payload={"source_event_key": "issue_comment:999"},
    )

    with pytest.raises(RuntimeError, match="source_event_key mismatch"):
        reconcile.build_deferred_comment_replay_context(
            payload,
            expected_event_name="issue_comment",
            live_comment_endpoint="issues/comments/210",
        )


def test_build_deferred_review_replay_context_returns_typed_context():
    payload = reconcile.DeferredReviewPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Review Submitted Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            source_run_id=500,
            source_run_attempt=2,
            source_event_name="pull_request_review",
            source_event_action="submitted",
            source_event_key="pull_request_review:11",
        ),
        pr_number=42,
        review_id=11,
        source_submitted_at="2026-03-17T10:00:00Z",
        source_review_state="COMMENTED",
        source_commit_id="head-1",
        actor_login="alice",
        raw_payload={"source_event_key": "pull_request_review:11"},
    )

    context = reconcile.build_deferred_review_replay_context(
        payload,
        expected_event_action="submitted",
    )

    assert isinstance(context, reconcile.DeferredReviewReplayContext)
    assert context.review_id == 11
    assert context.pr_number == 42
    assert context.actor_login == "alice"


def test_build_deferred_review_replay_context_rejects_mismatched_source_event_key():
    payload = reconcile.DeferredReviewPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Review Submitted Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            source_run_id=500,
            source_run_attempt=2,
            source_event_name="pull_request_review",
            source_event_action="submitted",
            source_event_key="pull_request_review:99",
        ),
        pr_number=42,
        review_id=11,
        source_submitted_at="2026-03-17T10:00:00Z",
        source_review_state="COMMENTED",
        source_commit_id="head-1",
        actor_login="alice",
        raw_payload={"source_event_key": "pull_request_review:99"},
    )

    with pytest.raises(RuntimeError, match="source_event_key mismatch"):
        reconcile.build_deferred_review_replay_context(
            payload,
            expected_event_action="submitted",
        )


def test_parse_deferred_context_payload_returns_typed_observer_noop_payload():
    payload = {
        "schema_version": 1,
        "kind": "observer_noop",
        "reason": "not a command",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 610,
        "source_run_attempt": 1,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": "issue_comment:210",
        "pr_number": 42,
    }

    parsed = reconcile.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reconcile.ObserverNoopPayload)
    assert parsed.reason == "not a command"
    assert parsed.pr_number == 42


def test_reconcile_active_review_entry_uses_explicit_head_repair_changed_field(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.maybe_record_head_observation_repair = lambda issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged")
    runtime.get_pull_request_reviews = lambda issue_number: []
    monkeypatch.setattr(reconcile, "refresh_reviewer_review_from_live_preferred_review", lambda bot, issue_number, review_data, **kwargs: (False, None))
    monkeypatch.setattr(reconcile, "_record_review_rebuild", lambda bot, state_obj, issue_number, review_data: False)

    message, success, changed = reconcile.reconcile_active_review_entry(runtime, state, 42, require_pull_request_context=True)

    assert success is True
    assert changed is False
    assert "no reconciliation transitions applied" in message


def test_parse_deferred_context_payload_rejects_unsupported_payload():
    with pytest.raises(RuntimeError, match="Unsupported deferred workflow_run payload"):
        reconcile.parse_deferred_context_payload({"schema_version": 2})


def test_validate_live_comment_replay_contract_reports_changed_for_command_ambiguity(monkeypatch):
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    payload = {
        "comment_id": 201,
        "comment_class": "command_only",
        "has_non_command_text": False,
        "source_event_key": "issue_comment:201",
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_created_at": "2026-03-17T10:00:00Z",
        "pr_number": 42,
        "source_run_id": 603,
        "source_run_attempt": 1,
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_artifact_name": "reviewer-bot-comment-context-603-attempt-1",
    }
    monkeypatch.setattr(
        reconcile,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )

    result = reconcile._validate_live_comment_replay_contract(
        FakeReviewerBotRuntime(monkeypatch),
        review,
        payload,
        "@guidelines-bot /claim",
    )

    assert result.live_classified is None
    assert result.changed is True
    assert result.failed_closed is True
    assert review["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"


def test_resolve_workflow_run_pr_number_fails_closed_when_pr_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "42")
    runtime.set_config_value("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "head-1")
    runtime.set_config_value("WORKFLOW_RUN_HEAD_SHA", "head-1")
    runtime.github_api_request = lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
        status_code=502,
        payload={"message": "bad gateway"},
        headers={},
        text="bad gateway",
        ok=False,
        failure_kind="server_error",
        retry_attempts=1,
        transport_error=None,
    )

    with pytest.raises(RuntimeError, match="Failed to fetch pull request #42 during workflow_run reconcile"):
        commands.resolve_workflow_run_pr_number(runtime)
