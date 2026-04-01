import json

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing
from tests.fixtures.reviewer_bot import make_state


def test_handle_workflow_run_event_returns_true_for_submitted_review_bookkeeping_only_mutations(
    tmp_path, monkeypatch
):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "bob"
    review["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}
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
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/11":
            return {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "pull_request_review:11" in review["reconciled_source_events"]
    assert "pull_request_review:11" not in review["deferred_gaps"]


def test_handle_workflow_run_event_persists_fail_closed_diagnostic_without_raising(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:12",
                "pr_number": 42,
                "review_id": 12,
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
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "pulls/42/reviews/12":
            return reviewer_bot.GitHubApiResult(
                status_code=502,
                payload={"message": "bad gateway"},
                headers={},
                text="bad gateway",
                ok=False,
                failure_kind="server_error",
                retry_attempts=1,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    gap = review["deferred_gaps"]["pull_request_review:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"


def test_deferred_comment_reconcile_returns_true_for_bookkeeping_only_mutations(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /queue"
    payload_path.write_text(
        json.dumps(
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
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "610")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(reviewer_bot.reconcile_module, "_handle_command", lambda *args, **kwargs: False)

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/210":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "issue_comment:210" in review["reconciled_source_events"]
    assert "issue_comment:210" not in review["deferred_gaps"]


def test_deferred_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:99",
                "pr_number": 42,
                "comment_id": 99,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: ({"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None),
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"]["semantic_key"] == "issue_comment:99"
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:99"]["reason"] == "reconcile_failed_closed"


def test_handle_workflow_run_event_rebuilds_completion_from_live_review_commit_id(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    payload_path = tmp_path / "deferred.json"
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
                "source_review_state": "APPROVED",
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
            "pulls/42": {"head": {"sha": "head-2"}},
            "pulls/42/reviews/11": {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "APPROVED",
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
                "state": "APPROVED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["current_cycle_completion"]["completed"] is False


def test_handle_workflow_run_event_refreshes_stale_stored_reviewer_review_to_current_head_preferred_review(
    tmp_path, monkeypatch
):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
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
                "source_event_key": "pull_request_review:99",
                "pr_number": 42,
                "review_id": 99,
                "source_submitted_at": "2026-03-17T11:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-0",
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

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/99":
            return {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"


def test_deferred_review_comment_reconcile_records_contributor_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "author reply in review thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 701,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:301",
                "pr_number": 42,
                "comment_id": 301,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
                "actor_id": 5,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-701-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "701")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/301":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    accepted = state["active_reviews"]["42"]["contributor_comment"]["accepted"]
    assert accepted is not None
    assert accepted["semantic_key"] == "pull_request_review_comment:301"


def test_deferred_review_comment_reconcile_records_reviewer_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "reviewer reply in thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 702,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:302",
                "pr_number": 42,
                "comment_id": 302,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T11:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-702-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "702")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/302":
            return {
                "body": live_body,
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:302"


def test_deferred_review_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 703,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:303",
                "pr_number": 42,
                "comment_id": 303,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-703-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "703")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: ({"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None),
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:303"
    assert review["deferred_gaps"]["pull_request_review_comment:303"]["reason"] == "reconcile_failed_closed"


def test_deferred_comment_reconcile_fails_closed_when_command_replay_is_ambiguous(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /claim"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 603,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:201",
                "pr_number": 42,
                "comment_id": 201,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "603")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/201":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
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
    command_calls = []
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_handle_command",
        lambda *args, **kwargs: command_calls.append("called") or True,
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert command_calls == []
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:201" not in state["active_reviews"]["42"]["reconciled_source_events"]
