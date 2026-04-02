import json

import pytest

pytestmark = pytest.mark.integration

from scripts import reviewer_bot
from tests.fixtures.app_harness import AppHarness
from tests.fixtures.reviewer_bot import make_state


def test_execute_run_workflow_run_bookkeeping_only_reconcile_still_saves_state(tmp_path, monkeypatch):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="pull_request_review",
        WORKFLOW_RUN_EVENT_ACTION="submitted",
    )

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
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_NAME="Reviewer Bot PR Review Submitted Observer",
        WORKFLOW_RUN_TRIGGERING_ID="700",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []
    synced_issue_numbers = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler(
        "handle_workflow_run_event",
        lambda current: reviewer_bot.collect_touched_item(42) or current["active_reviews"]["42"]["reconciled_source_events"].append("pull_request_review:11") or current["active_reviews"]["42"]["deferred_gaps"].pop("pull_request_review:11", None) or True,
    )
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review:11" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: synced_issue_numbers.extend(issue_numbers) or True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["pull_request_review:11"], "gap_present": False}]
    assert synced_issue_numbers == [42]

def test_execute_run_workflow_run_deferred_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="issue_comment",
        WORKFLOW_RUN_EVENT_ACTION="created",
    )

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
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_NAME="Reviewer Bot PR Comment Observer",
        WORKFLOW_RUN_TRIGGERING_ID="710",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))
    harness.stub_handler(
        "handle_workflow_run_event",
        lambda current: reviewer_bot.collect_touched_item(42) or current["active_reviews"]["42"]["reconciled_source_events"].append("issue_comment:210") or current["active_reviews"]["42"]["deferred_gaps"].pop("issue_comment:210", None) or True,
    )
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "issue_comment:210" in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [{"reconciled": ["issue_comment:210"], "gap_present": False}]

def test_execute_run_workflow_run_deferred_review_comment_bookkeeping_only_reconcile_still_saves_state(
    tmp_path, monkeypatch
):
    harness = AppHarness(monkeypatch)
    harness.set_event(
        EVENT_NAME="workflow_run",
        EVENT_ACTION="completed",
        WORKFLOW_RUN_EVENT="pull_request_review_comment",
        WORKFLOW_RUN_EVENT_ACTION="created",
    )

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
    harness.set_event(
        DEFERRED_CONTEXT_PATH=str(payload_path),
        WORKFLOW_RUN_TRIGGERING_NAME="Reviewer Bot PR Review Comment Observer",
        WORKFLOW_RUN_TRIGGERING_ID="711",
        WORKFLOW_RUN_TRIGGERING_ATTEMPT="1",
        WORKFLOW_RUN_TRIGGERING_CONCLUSION="success",
    )

    save_snapshots = []

    harness.stub_lock(acquire=lambda: None, release=lambda: True)
    harness.stub_load_state(lambda *, fail_on_unavailable=False: state)
    harness.stub_pass_until(lambda current: (current, []))
    harness.stub_sync_members(lambda current: (current, []))

    harness.stub_handler(
        "handle_workflow_run_event",
        lambda current: reviewer_bot.collect_touched_item(42) or current["active_reviews"]["42"]["reconciled_source_events"].append("pull_request_review_comment:310") or current["active_reviews"]["42"]["deferred_gaps"].pop("pull_request_review_comment:310", None) or True,
    )
    harness.stub_save_state(
        lambda current: save_snapshots.append(
            {
                "reconciled": list(current["active_reviews"]["42"]["reconciled_source_events"]),
                "gap_present": "pull_request_review_comment:310"
                in current["active_reviews"]["42"]["deferred_gaps"],
            }
        )
        or True
    )
    harness.stub_sync_status_labels(lambda current, issue_numbers: True)

    result = reviewer_bot.execute_run(reviewer_bot.build_event_context())

    assert result.exit_code == 0
    assert save_snapshots == [
        {"reconciled": ["pull_request_review_comment:310"], "gap_present": False}
    ]
