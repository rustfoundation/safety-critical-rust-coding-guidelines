import pytest

from scripts import reviewer_bot
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

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.DeferredReviewPayload)
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

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.DeferredCommentPayload)
    assert parsed.identity.source_event_key == "issue_comment:210"
    assert parsed.comment_id == 210


def test_build_deferred_comment_replay_context_returns_typed_context():
    payload = reviewer_bot.reconcile_module.DeferredCommentPayload(
        identity=reviewer_bot.reconcile_module.DeferredArtifactIdentity(
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

    context = reviewer_bot.reconcile_module.build_deferred_comment_replay_context(
        payload,
        expected_event_name="issue_comment",
        live_comment_endpoint="issues/comments/210",
    )

    assert isinstance(context, reviewer_bot.reconcile_module.DeferredCommentReplayContext)
    assert context.comment_id == 210
    assert context.pr_number == 42
    assert context.source_freshness_eligible is True


def test_build_deferred_comment_replay_context_rejects_mismatched_source_event_key():
    payload = reviewer_bot.reconcile_module.DeferredCommentPayload(
        identity=reviewer_bot.reconcile_module.DeferredArtifactIdentity(
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
        reviewer_bot.reconcile_module.build_deferred_comment_replay_context(
            payload,
            expected_event_name="issue_comment",
            live_comment_endpoint="issues/comments/210",
        )


def test_build_deferred_review_replay_context_returns_typed_context():
    payload = reviewer_bot.reconcile_module.DeferredReviewPayload(
        identity=reviewer_bot.reconcile_module.DeferredArtifactIdentity(
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

    context = reviewer_bot.reconcile_module.build_deferred_review_replay_context(
        payload,
        expected_event_action="submitted",
    )

    assert isinstance(context, reviewer_bot.reconcile_module.DeferredReviewReplayContext)
    assert context.review_id == 11
    assert context.pr_number == 42
    assert context.actor_login == "alice"


def test_build_deferred_review_replay_context_rejects_mismatched_source_event_key():
    payload = reviewer_bot.reconcile_module.DeferredReviewPayload(
        identity=reviewer_bot.reconcile_module.DeferredArtifactIdentity(
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
        reviewer_bot.reconcile_module.build_deferred_review_replay_context(
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

    parsed = reviewer_bot.reconcile_module.parse_deferred_context_payload(payload)

    assert isinstance(parsed, reviewer_bot.reconcile_module.ObserverNoopPayload)
    assert parsed.reason == "not a command"
    assert parsed.pr_number == 42


def test_reconcile_active_review_entry_uses_explicit_head_repair_changed_field(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "refresh_reviewer_review_from_live_preferred_review",
        lambda bot, issue_number, review_data, **kwargs: (False, None),
    )
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )

    message, success, changed = reviewer_bot.reconcile_module.reconcile_active_review_entry(
        reviewer_bot,
        state,
        42,
        require_pull_request_context=True,
    )

    assert success is True
    assert changed is False
    assert "no reconciliation transitions applied" in message


def test_parse_deferred_context_payload_rejects_unsupported_payload():
    with pytest.raises(RuntimeError, match="Unsupported deferred workflow_run payload"):
        reviewer_bot.reconcile_module.parse_deferred_context_payload({"schema_version": 2})


def test_validate_live_comment_replay_contract_reports_changed_for_command_ambiguity(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
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
        reviewer_bot.reconcile_module,
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

    result = reviewer_bot.reconcile_module._validate_live_comment_replay_contract(
        reviewer_bot,
        review,
        payload,
        "@guidelines-bot /claim",
    )

    assert result.live_classified is None
    assert result.changed is True
    assert result.failed_closed is True
    assert review["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"


def test_resolve_workflow_run_pr_number_fails_closed_when_pr_unavailable(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "42")
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "head-1")
    monkeypatch.setenv("WORKFLOW_RUN_HEAD_SHA", "head-1")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to fetch pull request #42 during workflow_run reconcile"):
        reviewer_bot.resolve_workflow_run_pr_number()
