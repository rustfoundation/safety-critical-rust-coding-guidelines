from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from scripts.reviewer_bot_lib import commands, lifecycle, reconcile, review_state
from scripts.reviewer_bot_lib.config import GitHubApiResult
from scripts.reviewer_bot_lib.context import (
    ReconcileRectifyRuntimeContext,
    ReconcileWorkflowRuntimeContext,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reconcile_harness import ReconcileHarness, review_submitted_payload
from tests.fixtures.reviewer_bot import make_state


def test_parse_deferred_context_payload_returns_typed_review_payload():
    payload = review_submitted_payload(
        pr_number=42,
        review_id=11,
        source_event_key="pull_request_review:11",
        source_submitted_at="2026-03-17T10:00:00Z",
        source_review_state="COMMENTED",
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=500,
        source_run_attempt=2,
    )

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


@pytest.mark.parametrize(
    ("source_event_name", "source_event_action", "expected"),
    [
        ("issue_comment", "created", True),
        ("pull_request_review", "submitted", True),
        ("pull_request_review", "dismissed", True),
        ("pull_request_review_comment", "created", True),
        ("issue_comment", "deleted", False),
        ("pull_request_review", "edited", False),
        ("pull_request_review_comment", "edited", False),
        ("workflow_dispatch", "completed", False),
    ],
)
def test_mutating_workflow_run_source_action_matrix(source_event_name, source_event_action, expected):
    assert reconcile.supports_mutating_workflow_run_source_action(source_event_name, source_event_action) is expected


def test_handle_workflow_run_event_collects_touched_item_for_projection_followup(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    runtime.stub_deferred_payload(
        {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "trusted_direct_same_repo_human_comment",
            "source_workflow_name": "Reviewer Bot PR Comment Observer",
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "source_run_id": 610,
            "source_run_attempt": 1,
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "source_event_key": "issue_comment:210",
            "pr_number": 42,
        }
    )
    state = make_state(epoch="freshness_v15")

    result = reconcile.handle_workflow_run_event_result(runtime, state)

    assert result.state_changed is False
    assert result.touched_items == [42]
    assert result.projection_followup_needed is True
    assert runtime.drain_touched_items() == []
    assert "42" in state["active_reviews"]


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


def test_reconcile_deferred_comment_fail_closes_for_command_ambiguity(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    comment_body = "@guidelines-bot /claim"
    payload = reconcile.DeferredCommentPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Comment Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
            source_run_id=603,
            source_run_attempt=1,
            source_event_name="issue_comment",
            source_event_action="created",
            source_event_key="issue_comment:201",
        ),
        pr_number=42,
        comment_id=201,
        comment_class="command_only",
        has_non_command_text=False,
        source_body_digest=reconcile.digest_comment_body(comment_body),
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="alice",
        raw_payload={
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
            "source_body_digest": reconcile.digest_comment_body(comment_body),
            "actor_login": "alice",
        },
    )
    context = reconcile.build_deferred_comment_replay_context(
        payload,
        expected_event_name="issue_comment",
        live_comment_endpoint="issues/comments/201",
    )
    monkeypatch.setattr(
        reconcile,
        "_read_live_pr_replay_context",
        lambda bot, pr_number: SimpleNamespace(issue_author="dana", issue_labels=()),
    )
    monkeypatch.setattr(
        reconcile,
        "_read_reconcile_object",
        lambda bot, endpoint, *, label: {
            "body": comment_body,
            "user": {"login": "alice", "type": "User"},
            "author_association": "MEMBER",
            "performed_via_github_app": False,
        },
    )
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
    monkeypatch.setattr(
        reconcile,
        "process_comment_event",
        lambda *args, **kwargs: pytest.fail("ambiguous replay must fail closed before command application"),
    )

    changed = reconcile._reconcile_deferred_comment(runtime, state, review, context)

    assert changed is True
    assert review["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "no longer resolves to exactly one command" in review["deferred_gaps"]["issue_comment:201"]["diagnostic_summary"]


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


def test_read_reconcile_reviews_rejects_non_list_payload(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.get_pull_request_reviews = lambda issue_number: {"unexpected": True}

    with pytest.raises(reconcile.ReconcileReadError, match="payload invalid"):
        reconcile._read_reconcile_reviews(runtime, 42)


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

    assert reconcile._read_optional_reconcile_object(runtime, "pulls/42/reviews/11", label="live review #11") is None


def test_reconcile_harness_exposes_deferred_payload_store(monkeypatch):
    payload = review_submitted_payload(
        pr_number=42,
        review_id=11,
        source_event_key="pull_request_review:11",
        source_submitted_at="2026-03-17T10:00:00Z",
        source_review_state="COMMENTED",
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=500,
        source_run_attempt=2,
    )
    harness = ReconcileHarness(monkeypatch, payload)

    assert harness.deferred_payloads is harness.runtime.deferred_payloads


def test_reconcile_module_delegates_replay_decision_logic_to_core_policy():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")

    assert "from scripts.reviewer_bot_core import reconcile_replay_policy" in reconcile_text
    assert "reconcile_replay_policy.decide_comment_replay(" in reconcile_text
    assert "reconcile_replay_policy.decide_review_submitted_replay(" in reconcile_text
    assert "reconcile_replay_policy.decide_review_dismissed_replay(" in reconcile_text


@pytest.mark.parametrize(
    ("payload", "expected_handler_name"),
    [
        (
            {
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
            },
            "_handle_issue_comment_workflow_run",
        ),
        (
            review_submitted_payload(
                pr_number=42,
                review_id=11,
                source_event_key="pull_request_review:11",
                source_submitted_at="2026-03-17T10:00:00Z",
                source_review_state="COMMENTED",
                source_commit_id="head-1",
                actor_login="alice",
                source_run_id=500,
                source_run_attempt=2,
            ),
            "_handle_review_submitted_workflow_run",
        ),
        (
            {
                **review_submitted_payload(
                    pr_number=42,
                    review_id=12,
                    source_event_key="pull_request_review_dismissed:12",
                    source_submitted_at="2026-03-17T10:00:00Z",
                    source_review_state="COMMENTED",
                    source_commit_id="head-1",
                    actor_login="alice",
                    source_run_id=501,
                    source_run_attempt=1,
                ),
                "source_workflow_name": "Reviewer Bot PR Review Dismissed Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
                "source_event_action": "dismissed",
            },
            "_handle_review_dismissed_workflow_run",
        ),
        (
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 711,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:310",
                "pr_number": 42,
                "comment_id": 310,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc123",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            },
            "_handle_review_comment_workflow_run",
        ),
        (
            {
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
            },
            "_handle_observer_noop_workflow_run",
        ),
    ],
)
def test_workflow_run_dispatch_matrix_routes_supported_payloads(payload, expected_handler_name):
    parsed_payload = reconcile.parse_deferred_context_payload(payload)

    assert reconcile._workflow_run_handler_for_payload(parsed_payload).__name__ == expected_handler_name


def test_workflow_run_dispatch_matrix_rejects_unsupported_pairs():
    parsed_payload = reconcile.DeferredCommentPayload(
        identity=reconcile.DeferredArtifactIdentity(
            schema_version=2,
            source_workflow_name="Reviewer Bot PR Comment Observer",
            source_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
            source_run_id=610,
            source_run_attempt=1,
            source_event_name="issue_comment",
            source_event_action="edited",
            source_event_key="issue_comment:210",
        ),
        pr_number=42,
        comment_id=210,
        comment_class="command_only",
        has_non_command_text=False,
        source_body_digest="abc123",
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="bob",
        raw_payload={"source_event_key": "issue_comment:210"},
    )

    assert reconcile._workflow_run_handler_for_payload(parsed_payload) is None


def test_k1b_context_module_freezes_two_reconcile_runtime_subseams_not_one_mega_protocol():
    context_text = Path("scripts/reviewer_bot_lib/context.py").read_text(encoding="utf-8")

    assert "class ReconcileWorkflowRuntimeContext(Protocol):" in context_text
    assert "class ReconcileRectifyRuntimeContext(Protocol):" in context_text
    assert "class ReconcileAdaptersContext(Protocol):" in context_text
    assert "class ReconcileReviewStateAdapterContext(Protocol):" in context_text
    assert "class ReconcileWorkflowRuntimeContext(ReviewerBotContext, Protocol):" not in context_text
    assert "class ReconcileRectifyRuntimeContext(ReviewerBotContext, Protocol):" not in context_text


def test_k1c_workflow_run_reconcile_entrypoint_uses_frozen_workflow_runtime_protocol():
    hints = get_type_hints(reconcile.handle_workflow_run_event)

    assert hints["bot"] is ReconcileWorkflowRuntimeContext


def test_k1g_rectify_reconcile_entrypoints_use_finalized_rectify_runtime_protocol():
    reconcile_hints = get_type_hints(reconcile.reconcile_active_review_entry)
    rectify_hints = get_type_hints(reconcile.handle_rectify_command)
    rebuild_hints = get_type_hints(reconcile._record_review_rebuild)

    assert reconcile_hints["bot"] is ReconcileRectifyRuntimeContext
    assert rectify_hints["bot"] is ReconcileRectifyRuntimeContext
    assert rebuild_hints["bot"] is ReconcileRectifyRuntimeContext


def test_k1d_rectify_refresh_keeps_retained_owner_boundaries_explicit_in_reconcile_source():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")
    context_text = Path("scripts/reviewer_bot_lib/context.py").read_text(encoding="utf-8")

    assert "refresh_reviewer_review_from_live_preferred_review(" in reconcile_text
    assert "rebuild_pr_approval_state_result(" in reconcile_text
    assert "approval_policy.find_triage_approval_after(" in reconcile_text
    assert "def github_api_request(self, *args, **kwargs) -> Any: ..." in context_text
    assert "def github_api(self, *args, **kwargs) -> Any | None: ..." in context_text
    assert "def parse_github_timestamp(self, value: Any) -> datetime | None: ..." in context_text
    assert "def is_triage_or_higher(self, username: str) -> bool: ..." in context_text


def test_k1e_rectify_finalization_keeps_retained_approval_support_explicit_but_workflow_seam_unchanged():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")
    context_text = Path("scripts/reviewer_bot_lib/context.py").read_text(encoding="utf-8")

    assert "approval_policy.find_triage_approval_after(" in reconcile_text
    assert "bot.parse_github_timestamp(" in reconcile_text or "bot.parse_github_timestamp(" in Path("scripts/reviewer_bot_core/approval_policy.py").read_text(encoding="utf-8")
    assert "bot.is_triage_or_higher(" in Path("scripts/reviewer_bot_core/approval_policy.py").read_text(encoding="utf-8")
    assert "def parse_github_timestamp(self, value: Any) -> datetime | None: ..." in context_text
    assert "def is_triage_or_higher(self, username: str) -> bool: ..." in context_text
    workflow_block = context_text.split("class ReconcileWorkflowRuntimeContext(Protocol):", 1)[1].split("class ReconcileRectifyGitHubContext(Protocol):", 1)[0]
    assert "parse_github_timestamp" not in workflow_block
    assert "is_triage_or_higher" not in workflow_block
