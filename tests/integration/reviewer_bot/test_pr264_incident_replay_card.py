from copy import deepcopy

import pytest

from scripts.reviewer_bot_core import reviewer_response_policy
from scripts.reviewer_bot_lib import maintenance
from scripts.reviewer_bot_lib import overdue as overdue_lib
from tests.fixtures.reconcile_harness import ReconcileHarness, issue_comment_payload
from tests.fixtures.reviewer_bot import (
    accept_contributor_revision,
    accept_reviewer_comment,
    accept_reviewer_review,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi

pytestmark = pytest.mark.integration


def test_pr264_canonical_replay_card_keeps_plain_lgtm_diagnostic_only(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-26T04:58:03.401345+00:00",
        active_cycle_started_at="2026-02-26T04:58:03.401345+00:00",
    )
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=264,
            comment_id=210,
            source_event_key="issue_comment:210",
            body="LGTM",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-04-13T23:23:25Z",
            actor_login="iglesias",
            source_run_id=610,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=264, head_sha="head-live", author="manhatsu", labels=["coding guideline"], requested_reviewers=[])
    harness.add_issue_comment(
        comment_id=210,
        body="LGTM",
        author="iglesias",
        author_type="User",
        author_association="CONTRIBUTOR",
    )

    before_state = deepcopy(state)

    result = harness.handle_workflow_run_event_result(state)

    assert result.state_changed is False
    assert result.touched_items == [264]
    assert state == before_state
    assert review["reviewer_comment"].get("accepted") is None
    assert "issue_comment:210" not in review["sidecars"]["reconciled_source_events"]
    assert "issue_comment:210" not in review["sidecars"]["deferred_gaps"]
    assert all(call.method == "GET" for call in harness.github.request_calls)
    assert harness.github.api_calls == []

    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:77",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
    )
    accept_contributor_revision(
        review,
        semantic_key="pull_request_sync:264:head-live",
        timestamp="2026-03-18T12:09:36.450502+00:00",
        actor="manhatsu",
        head_sha="head-live",
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:4240237244",
        timestamp="2026-04-13T23:23:25Z",
        actor="iglesias",
    )
    legacy_comments = [
        {
            "id": 4240237244,
            "user": {"login": "iglesias"},
            "created_at": "2026-04-13T23:23:25Z",
            "body": "LGTM",
        },
        {
            "id": 4240517367,
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-04-14T00:44:23Z",
            "body": "⚠️ **Review Reminder**\n\n"
            "Hey @iglesias, it's been more than 14 days since you were assigned to review this.\n\n"
            "If no action is taken within 14 days, you may be transitioned from Producer to Observer status.",
        },
        {
            "id": 4240520000,
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-04-14T00:52:09Z",
            "body": "⚠️ **Review Reminder**\n\n"
            "Hey @iglesias, this review has already received its final transition notice.\n\n"
            "If no action is taken, the reviewer may be transitioned from Producer to Observer status.",
        },
    ]

    routes = RouteGitHubApi().add_request(
        "GET",
        "issues/264",
        status_code=200,
        payload={"number": 264, "state": "open", "pull_request": {}, "labels": []},
    ).add_request(
        "GET",
        "pulls/264",
        status_code=200,
        payload={
            **pull_request_payload(264, head_sha="head-live", author="manhatsu"),
            "requested_reviewers": [],
            "labels": [],
        },
    ).add_pull_request_reviews(
        264,
        [
            review_payload(77, state="COMMENTED", submitted_at="2026-03-18T01:09:05Z", commit_id="head-old", author="iglesias"),
            review_payload(501, state="APPROVED", submitted_at="2026-03-18T12:10:42Z", commit_id="head-live", author="plaindocs"),
        ],
    ).add_request(
        "GET",
        "issues/264/comments?per_page=100&page=1",
        status_code=200,
        payload=legacy_comments,
    )
    harness.runtime.github.stub(routes)

    overdue = maintenance.check_overdue_reviews(harness.runtime, state)
    response_state = harness.runtime.adapters.review_state.compute_reviewer_response_state(
        264,
        review,
        issue_snapshot={"number": 264, "state": "open", "pull_request": {}, "labels": []},
    )

    assert overdue == []
    response = reviewer_response_policy.to_reviewer_response_decision(
        {
            **response_state,
            "issue_number": 264,
            "current_reviewer": "iglesias",
        }
    )
    reminder_scan = overdue_lib.scan_reviewer_reminder_comments(legacy_comments)
    cadence = overdue_lib.derive_reminder_cadence_decision(
        response,
        receipt=None,
        reminder_scan=reminder_scan,
        now=harness.runtime.datetime.now(harness.runtime.timezone.utc),
        review_deadline_days=harness.runtime.REVIEW_DEADLINE_DAYS,
        transition_period_days=harness.runtime.TRANSITION_PERIOD_DAYS,
    )
    effective = reviewer_response_policy.apply_reminder_cadence_overlay(response, cadence)
    assert response_state["state"] == "awaiting_reviewer_response"
    assert effective.response_state == "reviewer_reassignment_needed"
    assert effective.suppression_reason == "legacy_duplicate_reminders_exhausted"
