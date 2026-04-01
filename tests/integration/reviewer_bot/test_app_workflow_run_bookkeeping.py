import json
import pytest

pytestmark = pytest.mark.integration

from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state

def test_execute_run_workflow_run_bookkeeping_only_reconcile_still_saves_state(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "submitted")

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
                "source_run_id": 700,
                "source_run_attempt": 1,
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
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "700")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []
    synced_issue_numbers = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
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
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review:11" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True,
    )

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["pull_request_review:11"], "gap_present": False}]
    assert synced_issue_numbers == [42]

def test_execute_run_workflow_run_deferred_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "created")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 710,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:210",
                "pr_number": 42,
                "comment_id": 210,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": reviewer_bot.comment_routing_module._digest_body("@guidelines-bot /queue"),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "710")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot.reconcile_module, "_handle_command", lambda *args, **kwargs: False)

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/210":
            return {
                "body": "@guidelines-bot /queue",
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "issue_comment:210" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["issue_comment:210"], "gap_present": False}]

def test_execute_run_workflow_run_deferred_review_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "created")

    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["pull_request_review_comment:310"] = {"reason": "artifact_missing"}

    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
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
                "source_body_digest": reviewer_bot.comment_routing_module._digest_body("review comment body"),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "711")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    save_snapshots = []

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current: (current, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current: (current, []))

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/310":
            return {
                "body": "review comment body",
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
                "created_at": "2026-03-17T10:00:00Z",
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "save_state",
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review_comment:310"
                in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True,
    )
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current, issue_numbers: True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [
        {"reconciled": ["pull_request_review_comment:310"], "gap_present": False}
    ]
