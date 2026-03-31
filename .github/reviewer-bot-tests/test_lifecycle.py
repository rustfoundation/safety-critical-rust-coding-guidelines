import json

import pytest
from factories import make_state

from scripts import reviewer_bot


def test_handle_pull_request_target_synchronize_returns_true_for_head_only_mutation(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_head_sha"] = "head-1"
    review["contributor_revision"]["seen_keys"] = ["pull_request_sync:42:head-2"]
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("PR_HEAD_SHA", "head-2")
    monkeypatch.setenv("EVENT_CREATED_AT", "2026-03-17T10:00:00Z")

    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data: (None, None),
    )

    assert reviewer_bot.handle_pull_request_target_synchronize(state) is True
    assert review["active_head_sha"] == "head-2"

def test_pr_comment_direct_path_is_epoch_gated(monkeypatch):
    state = make_state(epoch="legacy_v14")
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    assert reviewer_bot.handle_comment_event(state) is False

def test_check_overdue_reviews_skips_transition_after_transition_notice_sent(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []

def test_handle_transition_notice_records_transition_notice_sent_at_once(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append((issue_number, body)) or True)
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is True
    assert review["transition_notice_sent_at"] is not None
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is False
    assert len(posted) == 1

def test_handle_transition_notice_message_does_not_claim_reassignment(monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is True
    assert "reassigned to the next person in the queue" not in posted[0]
    assert "/pass" in posted[0]

def test_reviewer_comment_clears_warning_and_transition_notice_markers(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    assert reviewer_bot.handle_comment_event(state) is True
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None

def test_scheduled_check_backfills_transition_notice_without_reposting(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
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
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"pull_request": {}})
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    def fake_api(method, endpoint, data=None):
        if endpoint == "issues/42/comments?per_page=100":
            return [
                {
                    "id": 99,
                    "created_at": "2026-03-25T15:22:42Z",
                    "body": "🔔 **Transition Period Ended**\n\nExisting notice",
                    "user": {"login": "github-actions[bot]"},
                }
            ]
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_api)
    assert reviewer_bot.handle_scheduled_check(state) is True
    assert review["transition_notice_sent_at"] == "2026-03-25T15:22:42Z"
    assert posted == []

def test_maybe_record_head_observation_repair_skips_unavailable_without_mutation(monkeypatch):
    review_data = {
        "active_head_sha": "head-1",
        "contributor_revision": {"accepted": None},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
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

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result == reviewer_bot.lifecycle_module.HeadObservationRepairResult(
        changed=False,
        outcome="skipped_unavailable",
        failure_kind="server_error",
        reason="pull_request_unavailable",
    )
    assert review_data["active_head_sha"] == "head-1"

def test_maybe_record_head_observation_repair_reports_not_found(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=404,
            payload={"message": "missing"},
            headers={},
            text="missing",
            ok=False,
            failure_kind="not_found",
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "skipped_not_found"
    assert result.failure_kind == "not_found"

def test_maybe_record_head_observation_repair_reports_invalid_payload(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "open", "head": {}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "invalid_live_payload"
    assert result.reason == "pull_request_head_unavailable"

def test_maybe_record_head_observation_repair_skips_not_open(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "closed", "head": {"sha": "head-1"}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "skipped_not_open"

def test_maybe_record_head_observation_repair_records_changed_head_once(monkeypatch):
    review_data = {
        "active_head_sha": "head-1",
        "contributor_revision": {"accepted": None},
        "current_cycle_completion": {"completed": True},
        "current_cycle_write_approval": {"has_write_approval": True},
        "review_completed_at": "2026-03-10T00:00:00Z",
        "review_completed_by": "alice",
        "review_completion_source": "live_review_rebuild",
    }
    accepted = []
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "open", "head": {"sha": "head-2"}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_channel_event",
        lambda review_data, channel, **kwargs: accepted.append((channel, kwargs)) or True,
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "changed"
    assert result.changed is True
    assert review_data["active_head_sha"] == "head-2"
    assert accepted[0][0] == "contributor_revision"
    assert accepted[0][1]["semantic_key"] == "pull_request_head_observed:42:head-2"
    assert review_data["current_cycle_completion"] == {}
    assert review_data["current_cycle_write_approval"] == {}
    assert review_data["review_completed_at"] is None

def test_handle_issue_or_pr_opened_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps(["coding guideline"]))
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    with pytest.raises(RuntimeError, match="Unable to determine assignees"):
        reviewer_bot.handle_issue_or_pr_opened(state)

def test_issue_edit_by_author_records_contributor_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("SENDER_LOGIN", "dana")
    monkeypatch.setenv("ISSUE_TITLE", "New title")
    monkeypatch.setenv("ISSUE_BODY", "body")
    monkeypatch.setenv("ISSUE_CHANGES_TITLE_FROM", "Old title")
    monkeypatch.setenv("ISSUE_CHANGES_BODY_FROM", "body")
    monkeypatch.setenv("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    assert reviewer_bot.handle_issue_edited_event(state) is True
    accepted = review["contributor_comment"]["accepted"]
    assert accepted["semantic_key"].startswith("issues_edit_title:42:")

def test_workflow_run_review_submission_clears_warning_and_transition_notice_markers(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"head": {"sha": "head-2"}, "user": {"login": "dana"}, "labels": []},
            "pulls/42/reviews/11": {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None

def test_maybe_record_head_observation_repair_uses_github_api_fallback_after_system_exit(monkeypatch):
    review_data = {
        "active_head_sha": "head-0",
        "contributor_revision": {"accepted": None},
    }
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_channel_event",
        lambda review_data, channel, **kwargs: True,
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.changed is True
    assert result.outcome == "changed"
    assert review_data["active_head_sha"] == "head-1"
