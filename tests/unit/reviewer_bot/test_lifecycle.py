import json
from pathlib import Path

import pytest

from scripts.reviewer_bot_lib import (
    comment_routing,
    event_inputs,
    lifecycle,
    maintenance,
    maintenance_schedule,
    review_state,
    reviews,
)
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi


def test_handle_pull_request_target_synchronize_returns_true_for_head_only_mutation(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_head_sha"] = "head-1"
    review["current_cycle_reviewer_handoff"] = {
        "source_event_key": "issue_comment:100",
        "timestamp": "2026-03-17T09:00:00Z",
        "actor": "alice",
        "command_name": "feedback",
        "reviewed_head_sha": "head-1",
    }
    review["contributor_revision"]["seen_keys"] = ["pull_request_sync:42:head-2"]
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("PR_HEAD_SHA", "head-2")
    runtime.set_config_value("PR_UPDATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setattr(reviews, "rebuild_pr_approval_state", lambda bot, issue_number, review_data: (None, None))

    assert lifecycle.handle_pull_request_target_synchronize(runtime, state) is True
    assert review["active_head_sha"] == "head-2"
    assert review["current_cycle_reviewer_handoff"] is None


def test_pr_comment_direct_path_is_epoch_gated(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state(epoch="legacy_v14")
    entry = review_state.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-router.yml",
        github_ref="refs/heads/main",
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="dana",
    )

    assert comment_routing.handle_comment_event(harness.runtime, state, request, trust_context) is False


def test_check_overdue_reviews_skips_transition_after_transition_notice_sent(monkeypatch):
    github = (
        RouteGitHubApi()
        .add_request(
            "GET",
            "issues/42",
            status_code=200,
            payload={"number": 42, "state": "open", "pull_request": {}, "labels": []},
        )
        .add_request(
            "GET",
            "pulls/42",
            status_code=200,
            payload={"number": 42, "state": "open", "requested_reviewers": [{"login": "alice"}]},
        )
        .add_request(
            "GET",
            "issues/42/comments?per_page=100&page=1",
            status_code=200,
            payload=[],
        )
    )
    runtime = FakeReviewerBotRuntime(monkeypatch, github=github)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    runtime.get_pull_request_reviews = lambda issue_number: []

    assert maintenance.check_overdue_reviews(runtime, state) == []


def test_handle_transition_notice_records_transition_notice_sent_at_once_without_external_config(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    posted = []
    runtime.github.post_comment_result = (
        lambda issue_number, body: posted.append((issue_number, body))
        or runtime.GitHubApiResult(201, {}, {}, "created", True, None, 0, None)
    )

    assert lifecycle.handle_transition_notice(runtime, state, 42, "alice") is True
    assert review["transition_notice_sent_at"] is not None
    assert lifecycle.handle_transition_notice(runtime, state, 42, "alice") is False
    assert len(posted) == 1


def test_handle_transition_notice_message_does_not_claim_reassignment(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    review_state.ensure_review_entry(state, 42, create=True)
    posted = []
    runtime.github.post_comment_result = (
        lambda issue_number, body: posted.append(body)
        or runtime.GitHubApiResult(201, {}, {}, "created", True, None, 0, None)
    )

    assert lifecycle.handle_transition_notice(runtime, state, 42, "alice") is True
    assert "reassigned to the next person in the queue" not in posted[0]
    assert "/pass" in posted[0]


def test_l1_fake_runtime_and_bootstrap_keep_override_wiring_explicit_without_canonical_introspection():
    fake_runtime_text = Path("tests/fixtures/fake_runtime.py").read_text(encoding="utf-8")
    bootstrap_text = Path("scripts/reviewer_bot_lib/bootstrap_runtime.py").read_text(encoding="utf-8")

    assert "def get_pull_request_reviews(" in fake_runtime_text
    assert "def rebuild_pr_approval_state(" in fake_runtime_text
    assert "def rebuild_pr_approval_state(" in bootstrap_text
    assert "_mark_canonical" not in bootstrap_text


def test_plain_reviewer_comment_does_not_clear_warning_or_transition_notice(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-router.yml",
        github_ref="refs/heads/main",
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="dana",
    )
    harness.runtime.github.get_issue_assignees = lambda issue_number, is_pull_request=None: ["alice"]

    assert comment_routing.handle_comment_event(harness.runtime, state, request, trust_context) is False
    assert review["transition_warning_sent"] == "2026-03-10T00:00:00Z"
    assert review["transition_notice_sent_at"] == "2026-03-25T00:00:00Z"


def test_reviewer_comment_does_not_count_as_reviewer_activity_when_live_assignee_differs(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-router.yml",
        github_ref="refs/heads/main",
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="dana",
    )
    harness.runtime.github.get_issue_assignees = lambda issue_number, is_pull_request=None: ["bob"]

    assert comment_routing.handle_comment_event(harness.runtime, state, request, trust_context) is False
    assert review["transition_warning_sent"] == "2026-03-10T00:00:00Z"
    assert review["transition_notice_sent_at"] == "2026-03-25T00:00:00Z"


def test_scheduled_check_backfills_markerized_transition_notice_without_reposting(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    monkeypatch.setattr(maintenance_schedule, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(review_state, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data, *, reviews=None: False)
    monkeypatch.setattr(maintenance_schedule, "maybe_record_head_observation_repair", lambda bot, issue_number, review_data: lifecycle.HeadObservationRepairResult(changed=False, outcome="unchanged"))
    monkeypatch.setattr(
        maintenance_schedule,
        "check_overdue_reviews",
        lambda bot, state: [
            {
                "issue_number": 42,
                "reviewer": "alice",
                "days_overdue": 20,
                "days_since_warning": 15,
                "needs_warning": False,
                "needs_transition": True,
            }
        ],
    )
    runtime.get_pull_request_reviews = lambda issue_number: []
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"pull_request": {}}
    posted = []
    runtime.github.post_comment_result = (
        lambda issue_number, body: posted.append(body)
        or runtime.GitHubApiResult(201, {}, {}, "created", True, None, 0, None)
    )
    runtime.github.list_issue_comments_result = lambda issue_number, page=1, per_page=100: runtime.GitHubApiResult(
        200,
        [
            {
                "id": 99,
                "created_at": "2026-03-25T15:22:42Z",
                "body": "<!-- reviewer-bot:transition-notice:v1 issue=42 reviewer=alice -->\n\n🔔 **Transition Period Ended**\n\nExisting notice",
                "user": {"login": "github-actions[bot]"},
            }
        ],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    assert maintenance.handle_scheduled_check_result(runtime, state).state_changed is True
    assert review["transition_notice_sent_at"] == "2026-03-25T15:22:42Z"
    assert posted == []


def test_maybe_record_head_observation_repair_skips_unavailable_without_mutation(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    runtime.github_api_request = lambda method, endpoint, **kwargs: GitHubApiResult(
        status_code=502,
        payload={"message": "bad gateway"},
        headers={},
        text="bad gateway",
        ok=False,
        failure_kind="server_error",
        retry_attempts=1,
        transport_error=None,
    )

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result == lifecycle.HeadObservationRepairResult(
        changed=False,
        outcome="skipped_unavailable",
        failure_kind="server_error",
        reason="pull_request_unavailable",
    )
    assert review_data["active_head_sha"] == "head-1"


def test_maybe_record_head_observation_repair_reports_not_found(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    runtime.github_api_request = lambda method, endpoint, **kwargs: GitHubApiResult(
        status_code=404,
        payload={"message": "missing"},
        headers={},
        text="missing",
        ok=False,
        failure_kind="not_found",
        retry_attempts=0,
        transport_error=None,
    )

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result.outcome == "skipped_not_found"
    assert result.failure_kind == "not_found"


def test_maybe_record_head_observation_repair_reports_invalid_payload(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    runtime.github_api_request = lambda method, endpoint, **kwargs: GitHubApiResult(
        status_code=200,
        payload={"state": "open", "head": {}},
        headers={},
        text="ok",
        ok=True,
        failure_kind=None,
        retry_attempts=0,
        transport_error=None,
    )

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result.outcome == "invalid_live_payload"
    assert result.reason == "pull_request_head_unavailable"


def test_maybe_record_head_observation_repair_skips_not_open(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    runtime.github_api_request = lambda method, endpoint, **kwargs: GitHubApiResult(
        status_code=200,
        payload={"state": "closed", "head": {"sha": "head-1"}},
        headers={},
        text="ok",
        ok=True,
        failure_kind=None,
        retry_attempts=0,
        transport_error=None,
    )

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result.outcome == "skipped_not_open"


def test_maybe_record_head_observation_repair_records_changed_head_once(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {
        "active_head_sha": "head-1",
        "contributor_revision": {"accepted": None},
        "current_cycle_reviewer_handoff": {
            "source_event_key": "issue_comment:100",
            "timestamp": "2026-03-17T09:00:00Z",
            "actor": "alice",
            "command_name": "feedback",
            "reviewed_head_sha": "head-1",
        },
        "current_cycle_completion": {"completed": True},
        "current_cycle_write_approval": {"has_write_approval": True},
        "review_completed_at": "2026-03-10T00:00:00Z",
        "review_completed_by": "alice",
        "review_completion_source": "live_review_rebuild",
    }
    accepted = []
    runtime.github_api_request = lambda method, endpoint, **kwargs: GitHubApiResult(
        status_code=200,
        payload={"state": "open", "head": {"sha": "head-2"}},
        headers={},
        text="ok",
        ok=True,
        failure_kind=None,
        retry_attempts=0,
        transport_error=None,
    )
    monkeypatch.setattr(lifecycle, "accept_channel_event", lambda review_data, channel, **kwargs: accepted.append((channel, kwargs)) or True)

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result.outcome == "changed"
    assert result.changed is True
    assert review_data["active_head_sha"] == "head-2"
    assert review_data["current_cycle_reviewer_handoff"] is None
    assert accepted[0][0] == "contributor_revision"
    assert accepted[0][1]["semantic_key"] == "pull_request_head_observed:42:head-2"
    assert review_data["current_cycle_completion"] == {}
    assert review_data["current_cycle_write_approval"] == {}
    assert review_data["review_completed_at"] is None


def test_handle_issue_or_pr_opened_fails_closed_when_assignees_unavailable(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    runtime.set_config_value("EVENT_ACTION", "opened")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))
    runtime.set_config_value("ISSUE_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: None

    with pytest.raises(RuntimeError, match="Unable to determine assignees"):
        lifecycle.handle_issue_or_pr_opened(runtime, state)


def test_handle_issue_or_pr_opened_does_not_mutate_reviewer_state_on_assignment_failure(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    runtime.set_config_value("EVENT_ACTION", "opened")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))
    runtime.set_config_value("ISSUE_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: []
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )
    runtime.adapters.queue.get_next_reviewer = lambda state, skip_usernames=None: "alice"
    runtime.github.assign_issue_assignee = lambda issue_number, username: runtime.AssignmentAttempt(
        success=False,
        status_code=502,
        exhausted_retryable_failure=True,
        failure_kind="server_error",
    )
    runtime.github.post_comment = lambda issue_number, body: True

    assert lifecycle.handle_issue_or_pr_opened(runtime, state) is True
    review = review_state.ensure_review_entry(state, 42)
    assert review is not None
    assert review.get("current_reviewer") is None
    assert review["sidecars"]["repair_markers"]["assignment_confirm_read"]["reason"] == "final_assignee_mismatch"


def test_handle_issue_or_pr_opened_adopts_existing_single_live_assignee(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    runtime.set_config_value("EVENT_ACTION", "opened")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))
    runtime.set_config_value("ISSUE_CREATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: ["alice"]
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    assert lifecycle.handle_issue_or_pr_opened(runtime, state) is True
    review = review_state.ensure_review_entry(state, 42)
    assert review is not None
    assert review["current_reviewer"] == "alice"
    assert review["assigned_at"] == "2026-03-17T10:00:00+00:00"


def test_handle_assigned_event_clears_reviewer_authority_on_multiple_live_assignees(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime.set_config_value("EVENT_ACTION", "assigned")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: ["alice", "bob"]
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        ["alice", "bob"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    assert lifecycle.handle_assigned_event(runtime, state) is True
    assert review["current_reviewer"] is None


def test_handle_unassigned_event_clears_reviewer_authority_when_live_assignee_missing(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime.set_config_value("EVENT_ACTION", "unassigned")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: []
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    assert lifecycle.handle_unassigned_event(runtime, state) is True
    assert review["current_reviewer"] is None


def test_issue_edit_by_author_records_contributor_freshness(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime.set_config_value("EVENT_ACTION", "edited")
    runtime.set_config_value("IS_PULL_REQUEST", "false")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_AUTHOR", "dana")
    runtime.set_config_value("SENDER_LOGIN", "dana")
    runtime.set_config_value("ISSUE_TITLE", "New title")
    runtime.set_config_value("ISSUE_BODY", "body")
    runtime.set_config_value("ISSUE_CHANGES_TITLE_FROM", "Old title")
    runtime.set_config_value("ISSUE_CHANGES_BODY_FROM", "body")
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")

    assert lifecycle.handle_issue_edited_event(runtime, state) is True
    accepted = review["contributor_comment"]["accepted"]
    assert accepted["semantic_key"].startswith("issues_edit_title:42:")


def test_handle_labeled_event_signoff_only_completes_coding_guideline_issue(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("LABEL_NAME", "sign-off: create pr")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline", "sign-off: create pr"]))

    assert lifecycle.handle_labeled_event(runtime, state) is True
    assert review["review_completion_source"] == "issue_label: sign-off: create pr"


def test_handle_unlabeled_event_reopens_signoff_completion(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["review_completed_at"] = "2026-03-17T10:00:00Z"
    review["review_completed_by"] = "alice"
    review["review_completion_source"] = "issue_label: sign-off: create pr"
    review["current_cycle_completion"] = {"completed": True}
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("LABEL_NAME", "sign-off: create pr")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))

    assert lifecycle.handle_unlabeled_event(runtime, state) is True
    assert review["review_completed_at"] is None
    assert review["review_completion_source"] is None


def test_handle_reopened_event_reopens_done_completion(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["review_completed_at"] = "2026-03-17T10:00:00Z"
    review["review_completed_by"] = "alice"
    review["review_completion_source"] = "command: /done"
    review["current_cycle_completion"] = {"completed": True}
    runtime.set_config_value("EVENT_ACTION", "reopened")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["fls-audit"]))
    runtime.set_config_value("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    runtime.github.get_issue_assignees = lambda issue_number: []
    runtime.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: runtime.GitHubApiResult(
        200,
        [],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    assert lifecycle.handle_reopened_event(runtime, state) is True
    assert review["review_completed_at"] is None
    assert review["review_completion_source"] is None


def test_handle_issue_or_pr_opened_rejects_missing_lifecycle_timestamp(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    runtime.set_config_value("EVENT_ACTION", "opened")
    runtime.set_config_value("ISSUE_NUMBER", "42")
    runtime.set_config_value("ISSUE_LABELS", json.dumps(["coding guideline"]))

    with pytest.raises(event_inputs.InvalidEventInput, match="ISSUE_CREATED_AT must be non-empty for opened"):
        lifecycle.handle_issue_or_pr_opened(runtime, state)


def test_lifecycle_does_not_fallback_to_updated_at_or_now_for_event_authority():
    lifecycle_text = Path("scripts/reviewer_bot_lib/lifecycle.py").read_text(encoding="utf-8")

    assert "request.event_created_at or request.updated_at" not in lifecycle_text
    assert "request.updated_at or _now_iso()" not in lifecycle_text


def test_handle_closed_event_removes_reviewer_handoff_with_review_entry(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.ACTIVE_LEASE_CONTEXT = object()
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["current_cycle_reviewer_handoff"] = {
        "source_event_key": "issue_comment:100",
        "timestamp": "2026-03-17T10:00:00Z",
        "actor": "alice",
        "command_name": "feedback",
        "reviewed_head_sha": None,
    }
    runtime.set_config_value("ISSUE_NUMBER", "42")

    assert lifecycle.handle_closed_event(runtime, state) is True
    assert "42" not in state["active_reviews"]


def test_maybe_record_head_observation_repair_uses_github_api_fallback_after_system_exit(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    review_data = {"active_head_sha": "head-0", "contributor_revision": {"accepted": None}}
    runtime.github_api_request = lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1))
    runtime.github_api = lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}}
    monkeypatch.setattr(lifecycle, "accept_channel_event", lambda review_data, channel, **kwargs: True)

    result = lifecycle.maybe_record_head_observation_repair(runtime, 42, review_data)

    assert result.changed is True
    assert result.outcome == "changed"
    assert review_data["active_head_sha"] == "head-1"
