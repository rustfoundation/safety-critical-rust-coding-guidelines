from copy import deepcopy

import pytest

from scripts.reviewer_bot_lib import reconcile
from scripts.reviewer_bot_lib.comment_application import digest_comment_body
from tests.fixtures.reconcile_harness import (
    ReconcileHarness,
    issue_comment_payload,
    review_comment_payload,
    review_dismissed_payload,
    review_submitted_payload,
)
from tests.fixtures.reviewer_bot import (
    accept_reviewer_review,
    make_state,
    make_tracked_review_state,
    review_payload,
)

pytestmark = pytest.mark.integration


def _deferred_gaps(review: dict) -> dict:
    return review["sidecars"]["deferred_gaps"]


def _reconciled_source_events(review: dict) -> dict:
    return review["sidecars"]["reconciled_source_events"]


def _legacy_review_comment_payload(
    *,
    pr_number: int = 42,
    comment_id: int,
    source_event_key: str,
    source_body_digest: str,
    source_created_at: str = "2026-03-17T10:00:00Z",
    actor_login: str = "alice",
    actor_id: int = 6,
    source_run_id: int,
    source_run_attempt: int = 1,
) -> dict:
    return {
        "schema_version": 2,
        "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_event_name": "pull_request_review_comment",
        "source_event_action": "created",
        "source_event_key": source_event_key,
        "pr_number": pr_number,
        "comment_id": comment_id,
        "comment_class": "plain_text",
        "has_non_command_text": True,
        "source_body_digest": source_body_digest,
        "source_created_at": source_created_at,
        "actor_login": actor_login,
        "actor_id": actor_id,
    }


C4C_DELETION_MANIFEST = [
    "inline comment classification drift decision text in reconcile.py",
    "inline non-command text drift decision text in reconcile.py",
    "inline command-count replay decision text in reconcile.py",
]


def test_handle_workflow_run_event_returns_true_for_submitted_review_bookkeeping_only_mutations(
    monkeypatch,
):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="bob")
    _deferred_gaps(review)["pull_request_review:11"] = {"reason": "artifact_missing"}
    harness = ReconcileHarness(
        monkeypatch,
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
    )
    harness.stub_review_rebuild(changed=False)
    harness.stub_head_repair(changed=False)
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.add_review(
        pr_number=42,
        review_id=11,
        submitted_at="2026-03-17T10:00:00Z",
        state="COMMENTED",
        commit_id="head-1",
        author="alice",
    )

    assert harness.run(state) is True
    assert "pull_request_review:11" in _reconciled_source_events(review)
    assert _reconciled_source_events(review)["pull_request_review:11"]["reconciled_at"] == "2026-01-01T00:00:00+00:00"
    assert "pull_request_review:11" not in _deferred_gaps(review)


def test_late_workflow_run_reconcile_missing_row_is_diagnostic_safe_noop(monkeypatch):
    state = make_state()
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=210,
            source_event_key="issue_comment:210",
            body="@guidelines-bot /queue",
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=610,
            source_run_attempt=1,
        ),
    )

    result = reconcile.handle_workflow_run_event_result(harness.runtime, state)

    assert result == reconcile.WorkflowRunHandlerResult(True, [42])
    assert state["active_reviews"] == {}
    orphan = state["sidecars"]["orphaned_deferred_reconcile_events"]["issue_comment:210"]
    assert orphan["recovery_status"] == "orphaned_deferred_event"


@pytest.mark.parametrize(
    "payload",
    [
        issue_comment_payload(
            pr_number=42,
            comment_id=210,
            source_event_key="issue_comment:210",
            body="@guidelines-bot /queue",
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=610,
            source_run_attempt=1,
        ),
        review_comment_payload(
            pr_number=42,
            comment_id=310,
            source_event_key="pull_request_review_comment:310",
            body="plain text review comment",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=11,
            actor_class="repo_user_principal",
            pull_request_review_id=77,
            in_reply_to_id=0,
            source_run_id=711,
            source_run_attempt=1,
        ),
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
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at="2026-03-17T10:10:00Z",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    ],
)
def test_late_workflow_run_reconcile_closed_live_pr_keeps_row_diagnostic_safe_noop(monkeypatch, payload):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    _deferred_gaps(review)[payload["source_event_key"]] = {"reason": "artifact_missing"}
    before = deepcopy(review)
    harness = ReconcileHarness(monkeypatch, payload)
    harness.add_pull_request(pr_number=42, head_sha="head-1", state="closed")

    result = reconcile.handle_workflow_run_event_result(harness.runtime, state)

    assert result == reconcile.WorkflowRunHandlerResult(False, [])
    assert state["active_reviews"]["42"] == before
    assert harness.runtime.drain_touched_items() == []


def test_deferred_review_dismissal_replay_uses_source_dismissal_time(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    _deferred_gaps(review)["pull_request_review_dismissed:12"] = {"reason": "artifact_missing"}
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at="2026-03-17T10:10:00Z",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.stub_review_rebuild(changed=False)
    harness.stub_head_repair(changed=False)

    assert harness.run(state) is True
    assert review["review_dismissal"]["accepted"]["timestamp"] == "2026-03-17T10:10:00Z"
    assert "pull_request_review_dismissed:12" in _reconciled_source_events(review)
    assert "pull_request_review_dismissed:12" not in _deferred_gaps(review)
    assert "issues/42/timeline?per_page=100&page=1" not in harness.github.requested_endpoints()


def test_deferred_review_dismissal_replay_uses_exact_timeline_dismissed_at(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at=None,
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.github.add_request(
        "GET",
        "issues/42/timeline?per_page=100&page=1",
        status_code=200,
        payload=[
            {
                "event": "review_dismissed",
                "created_at": "2026-03-17T10:12:00Z",
                "dismissed_review": {"review_id": 12, "state": "commented"},
            }
        ],
    )
    harness.stub_review_rebuild(changed=False)
    harness.stub_head_repair(changed=False)

    assert harness.run(state) is True
    assert review["review_dismissal"]["accepted"]["timestamp"] == "2026-03-17T10:12:00Z"
    assert "pull_request_review_dismissed:12" in _reconciled_source_events(review)


def test_deferred_review_dismissal_replay_finds_exact_time_on_paginated_timeline(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at=None,
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    first_page = [
        {
            "event": "review_dismissed",
            "created_at": "2026-03-17T10:00:00Z",
            "dismissed_review": {"review_id": 99, "state": "commented"},
        }
        for _ in range(100)
    ]
    harness.github.add_request(
        "GET",
        "issues/42/timeline?per_page=100&page=1",
        status_code=200,
        payload=first_page,
    )
    harness.github.add_request(
        "GET",
        "issues/42/timeline?per_page=100&page=2",
        status_code=200,
        payload=[
            {
                "event": "review_dismissed",
                "created_at": "2026-03-17T10:12:00Z",
                "dismissed_review": {"review_id": 12, "state": "commented"},
            }
        ],
    )
    harness.stub_review_rebuild(changed=False)
    harness.stub_head_repair(changed=False)

    assert harness.run(state) is True

    assert review["review_dismissal"]["accepted"]["timestamp"] == "2026-03-17T10:12:00Z"
    assert "issues/42/timeline?per_page=100&page=1" in harness.github.requested_endpoints()
    assert "issues/42/timeline?per_page=100&page=2" in harness.github.requested_endpoints()


def test_deferred_review_dismissal_without_source_time_stays_diagnostic_only(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at=None,
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.github.add_request(
        "GET",
        "issues/42/timeline?per_page=100&page=1",
        status_code=200,
        payload=[
            {
                "event": "review_dismissed",
                "created_at": "2026-03-17T10:12:00Z",
                "dismissed_review": {"review_id": 99, "state": "commented"},
            }
        ],
    )

    assert harness.run(state) is True
    assert review["review_dismissal"]["accepted"] is None
    assert _reconciled_source_events(review) == {}
    gap = _deferred_gaps(review)["pull_request_review_dismissed:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert "lacks exact source dismissal time" in gap["diagnostic_summary"]
    assert "timeline_dismissal_event_not_found" in gap["diagnostic_summary"]


@pytest.mark.parametrize(
    ("source_dismissed_at", "timeline_payload", "expected_reason"),
    [
        ("not-a-timestamp", None, "payload_invalid_source_dismissed_at"),
        (
            None,
            [{"event": "review_dismissed", "created_at": "not-a-timestamp", "dismissed_review": {"review_id": 12}}],
            "timeline_event_invalid_created_at",
        ),
        (
            None,
            [{"event": "review_dismissed", "dismissed_review": {"review_id": 12}}],
            "timeline_event_missing_created_at",
        ),
        (
            None,
            [
                {"event": "review_dismissed", "created_at": "2026-03-17T10:12:00Z", "dismissed_review": {"review_id": 12}},
                {"event": "review_dismissed", "created_at": "2026-03-17T10:13:00Z", "dismissed_review": {"review_id": 12}},
            ],
            "ambiguous_timeline_dismissal_events",
        ),
    ],
)
def test_deferred_review_dismissal_without_valid_exact_time_stays_diagnostic_only(
    monkeypatch,
    source_dismissed_at,
    timeline_payload,
    expected_reason,
):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at=source_dismissed_at,
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    if timeline_payload is not None:
        harness.github.add_request(
            "GET",
            "issues/42/timeline?per_page=100&page=1",
            status_code=200,
            payload=timeline_payload,
        )

    assert harness.run(state) is True
    assert review["review_dismissal"]["accepted"] is None
    assert _reconciled_source_events(review) == {}
    gap = _deferred_gaps(review)["pull_request_review_dismissed:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert expected_reason in gap["diagnostic_summary"]
    if source_dismissed_at is not None:
        assert gap["source_dismissed_at"] == source_dismissed_at
        assert gap["source_event_created_at"] == source_dismissed_at


def test_deferred_review_dismissal_timeline_failure_stays_diagnostic_with_failure_kind(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_dismissed_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review_dismissed:12",
            source_dismissed_at=None,
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=502,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.add_request_failure(
        endpoint="issues/42/timeline?per_page=100&page=1",
        status_code=403,
        payload={"message": "resource not accessible by integration"},
        failure_kind="forbidden",
    )

    assert harness.run(state) is True

    gap = _deferred_gaps(review)["pull_request_review_dismissed:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "forbidden"
    assert "timeline_unavailable" in gap["diagnostic_summary"]


def test_handle_workflow_run_event_persists_fail_closed_diagnostic_without_raising(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_submitted_payload(
            pr_number=42,
            review_id=12,
            source_event_key="pull_request_review:12",
            source_submitted_at="2026-03-17T10:00:00Z",
            source_review_state="COMMENTED",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=501,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.add_request_failure(
        endpoint="pulls/42/reviews/12",
        status_code=502,
        payload={"message": "bad gateway"},
        failure_kind="server_error",
    )

    assert harness.run(state) is True
    gap = _deferred_gaps(review)["pull_request_review:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"


def test_deferred_comment_reconcile_returns_true_for_bookkeeping_only_mutations(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    _deferred_gaps(review)["issue_comment:210"] = {"reason": "artifact_missing"}
    live_body = "@guidelines-bot /queue"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=210,
            source_event_key="issue_comment:210",
            body=live_body,
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=610,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", labels=["coding guideline"])
    harness.add_issue_comment(
        comment_id=210,
        body=live_body,
        author="bob",
        author_type="User",
        author_association="MEMBER",
    )
    harness.stub_apply_comment_command(False)

    assert harness.run(state) is True
    assert "issue_comment:210" in _reconciled_source_events(review)
    assert _reconciled_source_events(review)["issue_comment:210"]["reconciled_at"] == "2026-01-01T00:00:00+00:00"
    assert "issue_comment:210" not in _deferred_gaps(review)


def test_deferred_comment_missing_live_object_preserves_source_time_freshness(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=99,
            source_event_key="issue_comment:99",
            body="stale body",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            source_run_id=501,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_request_failure(
        endpoint="issues/comments/99",
        status_code=404,
        payload={"message": "missing"},
        failure_kind="not_found",
    )

    assert harness.run(state) is True
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"] is None
    gap = state["active_reviews"]["42"]["sidecars"]["deferred_gaps"]["issue_comment:99"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00Z"
    assert gap["source_actor_login"] == "alice"
    assert gap["source_actor_id"] == 7001
    assert gap["source_actor_user_type"] == "User"
    assert gap["source_actor_sender_type"] == "User"
    assert gap["source_actor_performed_via_github_app"] is False
    assert gap["source_comment_id"] == 99


def test_handle_workflow_run_event_rebuilds_completion_from_live_review_commit_id(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    harness = ReconcileHarness(
        monkeypatch,
        review_submitted_payload(
            pr_number=42,
            review_id=11,
            source_event_key="pull_request_review:11",
            source_submitted_at="2026-03-17T10:00:00Z",
            source_review_state="APPROVED",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=500,
            source_run_attempt=2,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-2", author="dana")
    harness.add_review(
        pr_number=42,
        review_id=11,
        submitted_at="2026-03-17T10:00:00Z",
        state="APPROVED",
        commit_id="head-1",
        author="alice",
    )
    harness.add_reviews_page(
        pr_number=42,
        reviews=[
            review_payload(
                11,
                state="APPROVED",
                submitted_at="2026-03-17T10:00:00Z",
                commit_id="head-1",
                author="alice",
            )
        ],
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    assert review["current_cycle_completion"]["completed"] is False


def test_handle_workflow_run_event_refreshes_stale_stored_reviewer_review_to_current_head_preferred_review(
    monkeypatch,
):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    harness = ReconcileHarness(
        monkeypatch,
        review_submitted_payload(
            pr_number=42,
            review_id=99,
            source_event_key="pull_request_review:99",
            source_submitted_at="2026-03-17T11:00:00Z",
            source_review_state="COMMENTED",
            source_commit_id="head-0",
            actor_login="alice",
            source_run_id=500,
            source_run_attempt=2,
        ),
    )
    harness.add_pull_request(pr_number=42, head_sha="head-1", author="dana")
    harness.add_review(
        pr_number=42,
        review_id=99,
        submitted_at="2026-03-17T11:00:00Z",
        state="COMMENTED",
        commit_id="head-0",
        author="alice",
    )
    harness.add_reviews_page(
        pr_number=42,
        reviews=[
            review_payload(
                10,
                state="COMMENTED",
                submitted_at="2026-03-17T10:00:00Z",
                commit_id="head-1",
                author="alice",
            ),
            review_payload(
                99,
                state="COMMENTED",
                submitted_at="2026-03-17T11:00:00Z",
                commit_id="head-0",
                author="alice",
            ),
        ],
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"


def test_deferred_review_comment_reconcile_records_contributor_freshness(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "author reply in review thread"
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=301,
            source_event_key="pull_request_review_comment:301",
            body=live_body,
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="dana",
            actor_id=5,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=701,
            source_run_attempt=1,
            source_commit_id="head-1",
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_review_comment(
        comment_id=301,
        body=live_body,
        author="dana",
        author_type="User",
        author_association="CONTRIBUTOR",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    accepted = state["active_reviews"]["42"]["contributor_comment"]["accepted"]
    assert accepted is not None
    assert accepted["semantic_key"] == "pull_request_review_comment:301"


def test_deferred_review_comment_reconcile_keeps_reviewer_freshness_diagnostic_only(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "reviewer reply in thread"
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=302,
            source_event_key="pull_request_review_comment:302",
            body=live_body,
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T11:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=702,
            source_run_attempt=1,
            source_commit_id="head-1",
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_review_comment(
        comment_id=302,
        body=live_body,
        author="alice",
        author_type="User",
        author_association="MEMBER",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is False
    assert review["reviewer_comment"]["accepted"] is None
    assert "pull_request_review_comment:302" not in _reconciled_source_events(review)
    assert "pull_request_review_comment:302" not in _deferred_gaps(review)


def test_deferred_review_comment_missing_live_object_preserves_source_time_freshness(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=303,
            source_event_key="pull_request_review_comment:303",
            body="stale body",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=703,
            source_run_attempt=1,
            source_commit_id="head-1",
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_request_failure(
        endpoint="pulls/comments/303",
        status_code=404,
        payload={"message": "missing"},
        failure_kind="not_found",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    assert review["reviewer_comment"]["accepted"] is None
    gap = _deferred_gaps(review)["pull_request_review_comment:303"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00Z"
    assert gap["source_actor_login"] == "alice"
    assert gap["source_actor_id"] == 6
    assert gap["source_actor_user_type"] == "User"
    assert gap["source_actor_sender_type"] == "User"
    assert gap["source_actor_performed_via_github_app"] is False
    assert gap["source_comment_id"] == 303
    assert gap["source_commit_id"] == "head-1"


def test_deferred_review_comment_parse_failure_records_artifact_invalid_gap(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=304,
            source_event_key="pull_request_review_comment:304",
            body="review comment without head evidence",
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
            source_commit_id=None,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])

    assert harness.run(state) is True
    assert review["reviewer_comment"]["accepted"] is None
    gap = _deferred_gaps(review)["pull_request_review_comment:304"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["failure_kind"] == "invalid_payload"
    assert "source_commit_id must be a non-empty string" in gap["diagnostic_summary"]
    assert "source_commit_id" not in gap


def test_deferred_review_comment_parse_failure_validates_triggering_run_before_diagnostic(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=307,
            source_event_key="pull_request_review_comment:307",
            body="review comment without head evidence",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=707,
            source_run_attempt=1,
            source_commit_id=None,
        ),
    )
    harness.runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_ID", "999")

    with pytest.raises(RuntimeError, match="run_id mismatch"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_validates_triggering_attempt_before_diagnostic(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=308,
            source_event_key="pull_request_review_comment:308",
            body="review comment without head evidence",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=708,
            source_run_attempt=1,
            source_commit_id=None,
        ),
    )
    harness.runtime.set_config_value("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")

    with pytest.raises(RuntimeError, match="run_attempt mismatch"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_closed_live_pr_is_safe_noop(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=309,
            source_event_key="pull_request_review_comment:309",
            body="review comment without head evidence",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=709,
            source_run_attempt=1,
            source_commit_id=None,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", state="closed")

    result = harness.handle_workflow_run_event_result(state)

    assert result == reconcile.WorkflowRunHandlerResult(False, [])
    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_requires_recoverable_event_kind(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = review_comment_payload(
        pr_number=42,
        comment_id=310,
        source_event_key="pull_request_review_comment:310",
        body="review comment without head evidence",
        comment_class="plain_text",
        has_non_command_text=True,
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="alice",
        actor_id=6,
        actor_class="repo_user_principal",
        pull_request_review_id=10,
        in_reply_to_id=200,
        source_run_id=710,
        source_run_attempt=1,
        source_commit_id=None,
    )
    payload.pop("source_event_name")
    harness = ReconcileHarness(monkeypatch, payload)

    with pytest.raises(RuntimeError, match="source_event_name"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_rejects_unsupported_event_kind(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = review_comment_payload(
        pr_number=42,
        comment_id=311,
        source_event_key="pull_request:42",
        body="review comment without head evidence",
        comment_class="plain_text",
        has_non_command_text=True,
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="alice",
        actor_id=6,
        actor_class="repo_user_principal",
        pull_request_review_id=10,
        in_reply_to_id=200,
        source_run_id=711,
        source_run_attempt=1,
        source_commit_id=None,
    )
    payload["source_event_name"] = "pull_request"
    payload["source_event_action"] = "closed"
    harness = ReconcileHarness(monkeypatch, payload)

    with pytest.raises(RuntimeError, match="supported recoverable event kind"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_rejects_mismatched_source_object_key(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=312,
            source_event_key="pull_request_review_comment:999",
            body="review comment without head evidence",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=712,
            source_run_attempt=1,
            source_commit_id=None,
        ),
    )

    with pytest.raises(RuntimeError, match="source_event_key does not match recoverable object id"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_comment_parse_failure_rejects_invalid_recoverable_timestamp(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(
        monkeypatch,
        review_comment_payload(
            pr_number=42,
            comment_id=313,
            source_event_key="pull_request_review_comment:313",
            body="review comment without head evidence",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="not-a-timestamp",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=713,
            source_run_attempt=1,
            source_commit_id=None,
        ),
    )

    with pytest.raises(RuntimeError, match="timestamp is not parseable"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


@pytest.mark.parametrize(
    "payload",
    [
        issue_comment_payload(
            pr_number=42,
            comment_id=214,
            source_event_key="issue_comment:999",
            body="@guidelines-bot /queue",
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=718,
            source_run_attempt=1,
        ),
        review_comment_payload(
            pr_number=42,
            comment_id=314,
            source_event_key="pull_request_review_comment:999",
            body="review comment with mismatched key",
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="alice",
            actor_id=6,
            actor_class="repo_user_principal",
            pull_request_review_id=10,
            in_reply_to_id=200,
            source_run_id=719,
            source_run_attempt=1,
            source_commit_id="head-1",
        ),
        review_submitted_payload(
            pr_number=42,
            review_id=15,
            source_event_key="pull_request_review:999",
            source_submitted_at="2026-03-17T10:00:00Z",
            source_review_state="COMMENTED",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=720,
            source_run_attempt=1,
        ),
        review_dismissed_payload(
            pr_number=42,
            review_id=16,
            source_event_key="pull_request_review_dismissed:999",
            source_dismissed_at="2026-03-17T10:10:00Z",
            source_commit_id="head-1",
            actor_login="alice",
            source_run_id=721,
            source_run_attempt=1,
        ),
    ],
)
def test_strict_parse_rejects_source_object_key_mismatch_before_diagnostic(monkeypatch, payload):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    harness = ReconcileHarness(monkeypatch, payload)

    with pytest.raises(RuntimeError, match="source_event_key does not match recoverable object id"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_issue_comment_parse_failure_records_artifact_invalid_gap(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = issue_comment_payload(
        pr_number=42,
        comment_id=212,
        source_event_key="issue_comment:212",
        body="@guidelines-bot /queue",
        comment_class="command_only",
        has_non_command_text=False,
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="bob",
        source_run_id=714,
        source_run_attempt=1,
    )
    payload["comment_sender_type"] = ""
    harness = ReconcileHarness(monkeypatch, payload)
    harness.add_pull_request(pr_number=42, author="dana")

    assert harness.run(state) is True
    gap = _deferred_gaps(review)["issue_comment:212"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["source_comment_id"] == 212
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00Z"


def test_deferred_issue_comment_parse_failure_rejects_mismatched_source_object_key(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = issue_comment_payload(
        pr_number=42,
        comment_id=213,
        source_event_key="issue_comment:999",
        body="@guidelines-bot /queue",
        comment_class="command_only",
        has_non_command_text=False,
        source_created_at="2026-03-17T10:00:00Z",
        actor_login="bob",
        source_run_id=715,
        source_run_attempt=1,
    )
    payload["comment_sender_type"] = ""
    harness = ReconcileHarness(monkeypatch, payload)

    with pytest.raises(RuntimeError, match="source_event_key does not match recoverable object id"):
        harness.run(state)

    assert _deferred_gaps(review) == {}


def test_deferred_review_submitted_parse_failure_records_artifact_invalid_gap(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = review_submitted_payload(
        pr_number=42,
        review_id=13,
        source_event_key="pull_request_review:13",
        source_submitted_at="2026-03-17T10:00:00Z",
        source_review_state="COMMENTED",
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=716,
        source_run_attempt=1,
    )
    payload["schema_version"] = 4
    harness = ReconcileHarness(monkeypatch, payload)
    harness.add_pull_request(pr_number=42, author="dana")

    assert harness.run(state) is True
    gap = _deferred_gaps(review)["pull_request_review:13"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["source_review_id"] == 13
    assert gap["source_event_created_at"] == "2026-03-17T10:00:00Z"


def test_deferred_review_dismissed_parse_failure_records_artifact_invalid_gap(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    payload = review_dismissed_payload(
        pr_number=42,
        review_id=14,
        source_event_key="pull_request_review_dismissed:14",
        source_dismissed_at="2026-03-17T10:10:00Z",
        source_commit_id="head-1",
        actor_login="alice",
        source_run_id=717,
        source_run_attempt=1,
    )
    payload["schema_version"] = 4
    harness = ReconcileHarness(monkeypatch, payload)
    harness.add_pull_request(pr_number=42, author="dana")

    assert harness.run(state) is True
    gap = _deferred_gaps(review)["pull_request_review_dismissed:14"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["source_review_id"] == 14
    assert gap["source_event_created_at"] == "2026-03-17T10:10:00Z"


def test_deferred_legacy_review_comment_hydrates_source_commit_id_from_live_comment(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    original_body = "legacy review comment original body"
    live_body = "legacy review comment edited body"
    harness = ReconcileHarness(
        monkeypatch,
        _legacy_review_comment_payload(
            comment_id=305,
            source_event_key="pull_request_review_comment:305",
            source_body_digest=digest_comment_body(original_body),
            source_run_id=705,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_review_comment(
        comment_id=305,
        body=live_body,
        author="alice",
        author_type="User",
        author_association="MEMBER",
        commit_id="head-1",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    gap = _deferred_gaps(review)["pull_request_review_comment:305"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["failure_kind"] == "blocked_untrusted_source"
    assert "diagnostic_legacy_identity" in gap["diagnostic_summary"]
    assert review["reviewer_comment"]["accepted"] is None


def test_deferred_legacy_review_comment_without_live_commit_id_records_artifact_invalid(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "legacy review comment body"
    harness = ReconcileHarness(
        monkeypatch,
        _legacy_review_comment_payload(
            comment_id=306,
            source_event_key="pull_request_review_comment:306",
            source_body_digest=digest_comment_body(live_body),
            source_run_id=706,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", requested_reviewers=["alice"])
    harness.add_review_comment(
        comment_id=306,
        body=live_body,
        author="alice",
        author_type="User",
        author_association="MEMBER",
    )

    assert harness.run(state) is True
    assert review["reviewer_comment"]["accepted"] is None
    gap = _deferred_gaps(review)["pull_request_review_comment:306"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["failure_kind"] == "blocked_untrusted_source"
    assert "diagnostic_legacy_identity" in gap["diagnostic_summary"]
    assert "source_commit_id" not in gap


def test_deferred_comment_reconcile_fails_closed_when_command_replay_is_ambiguous(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "@guidelines-bot /claim"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=201,
            source_event_key="issue_comment:201",
            body=live_body,
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=603,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_issue_comment(
        comment_id=201,
        body=live_body,
        author="bob",
        author_type="User",
        author_association="MEMBER",
    )
    harness.stub_comment_classification(
        {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": live_body,
        }
    )
    command_calls = []

    def record_command_call(*args, **kwargs):
        command_calls.append("called")
        return True

    harness.stub_apply_comment_command(func=record_command_call)

    assert harness.run(state) is True
    assert command_calls == []
    assert state["active_reviews"]["42"]["sidecars"]["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:201" not in state["active_reviews"]["42"]["sidecars"]["reconciled_source_events"]


def test_deferred_comment_reconcile_hydrates_pr_author_context_for_contributor_freshness(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "reviewer-bot validation: contributor plain text comment"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=199,
            source_event_key="issue_comment:199",
            body=live_body,
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="dana",
            source_run_id=601,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana", labels=["coding guideline"])
    harness.add_issue_comment(
        comment_id=199,
        body=live_body,
        author="dana",
        author_type="User",
        author_association="CONTRIBUTOR",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:199"
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"] is None


def test_deferred_legacy_comment_reconcile_hydrates_live_pr_context_for_contributor_freshness(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "reviewer-bot validation: legacy contributor plain text comment"
    harness = ReconcileHarness(
        monkeypatch,
        {
            "schema_version": 2,
            "source_workflow_name": "Reviewer Bot PR Comment Router",
            "source_run_id": 621,
            "source_run_attempt": 1,
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "source_event_key": "issue_comment:211",
            "pr_number": 42,
            "comment_id": 211,
            "comment_class": "plain_text",
            "has_non_command_text": True,
            "source_body_digest": digest_comment_body(live_body),
            "source_created_at": "2026-03-17T10:00:00Z",
            "actor_login": "dana",
        },
    )
    harness.add_pull_request(pr_number=42, author="dana", labels=["coding guideline"])
    harness.add_issue_comment(
        comment_id=211,
        body=live_body,
        author="dana",
        author_type="User",
        author_association="CONTRIBUTOR",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    gap = _deferred_gaps(state["active_reviews"]["42"])["issue_comment:211"]
    assert gap["reason"] == "artifact_invalid"
    assert gap["failure_kind"] == "blocked_untrusted_source"
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"] is None
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"] is None


def test_deferred_comment_reconcile_uses_pr_assignment_semantics_for_claim(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "bob", "name": "Bob"}]
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "@guidelines-bot /claim"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=200,
            source_event_key="issue_comment:200",
            body=live_body,
            comment_class="command_only",
            has_non_command_text=False,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="bob",
            source_run_id=602,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(
        pr_number=42,
        author="dana",
        labels=["coding guideline"],
        requested_reviewers=["alice"],
    )
    harness.add_issue_comment(
        comment_id=200,
        body=live_body,
        author="bob",
        author_type="User",
        author_association="MEMBER",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"
    claim_contexts = []

    def apply_claim_command(bot, state_obj, request, classified, classify_issue_comment_actor=None):
        claim_contexts.append(
            {
                "issue_number": request.issue_number,
                "username": request.comment_author,
                "is_pull_request": request.is_pull_request,
                "issue_author": request.issue_author,
            }
        )
        state_obj["active_reviews"][str(request.issue_number)]["current_reviewer"] = request.comment_author
        return True

    harness.stub_apply_comment_command(func=apply_claim_command)
    harness.runtime.add_reaction = lambda *args, **kwargs: True

    assert harness.run(state) is True
    assert claim_contexts == [
        {
            "issue_number": 42,
            "username": "bob",
            "is_pull_request": True,
            "issue_author": "dana",
        }
    ]
    assert state["active_reviews"]["42"]["current_reviewer"] == "bob"


def test_deferred_comment_reconcile_records_failure_kind_when_live_comment_unavailable(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "reviewer-bot validation: contributor plain text comment"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=205,
            source_event_key="issue_comment:205",
            body=live_body,
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="dana",
            source_run_id=603,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_request_failure(
        endpoint="issues/comments/205",
        status_code=502,
        payload={"message": "bad gateway"},
        failure_kind="server_error",
    )

    assert harness.run(state) is True
    gap = state["active_reviews"]["42"]["sidecars"]["deferred_gaps"]["issue_comment:205"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"


def test_deferred_comment_reconcile_fails_closed_when_comment_classification_drifts(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    live_body = "reviewer-bot validation: contributor plain text comment"
    harness = ReconcileHarness(
        monkeypatch,
        issue_comment_payload(
            pr_number=42,
            comment_id=202,
            source_event_key="issue_comment:202",
            body=live_body,
            comment_class="plain_text",
            has_non_command_text=True,
            source_created_at="2026-03-17T10:00:00Z",
            actor_login="dana",
            source_run_id=604,
            source_run_attempt=1,
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_issue_comment(
        comment_id=202,
        body=live_body,
        author="dana",
        author_type="User",
        author_association="CONTRIBUTOR",
    )
    harness.stub_comment_classification(
        {
            "comment_class": "command_plus_text",
            "has_non_command_text": True,
            "command_count": 1,
            "command": "claim",
            "args": [],
            "normalized_body": live_body,
        }
    )
    harness.runtime.add_reaction = lambda *args, **kwargs: True
    harness.runtime.github.post_comment = lambda *args, **kwargs: True

    assert harness.run(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:202"
    assert state["active_reviews"]["42"]["sidecars"]["deferred_gaps"]["issue_comment:202"]["reason"] == "reconcile_failed_closed"
    assert state["active_reviews"]["42"]["sidecars"]["reconciled_source_events"] == {}


def test_c4c_reconcile_deletion_manifest_and_adapter_cleanup_are_explicit():
    with open("scripts/reviewer_bot_lib/reconcile.py", encoding="utf-8") as handle:
        module_text = handle.read()

    assert C4C_DELETION_MANIFEST == [
        "inline comment classification drift decision text in reconcile.py",
        "inline non-command text drift decision text in reconcile.py",
        "inline command-count replay decision text in reconcile.py",
    ]
    assert "classification changed from" not in module_text
    assert "non-command text classification drifted" not in module_text
    assert "no longer resolves to exactly one command" not in module_text
    assert "reconcile_replay_policy.decide_comment_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_submitted_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_dismissed_replay_plan(" in module_text


def test_d2_reconcile_replay_path_stays_decode_read_apply_orchestration_only():
    with open("scripts/reviewer_bot_lib/reconcile.py", encoding="utf-8") as handle:
        module_text = handle.read()

    assert "build_deferred_comment_replay_context(" in module_text
    assert "_read_live_comment_replay_context(" in module_text
    assert "process_comment_event(" in module_text
    assert "record_conversation_freshness(" in module_text
    assert "mark_reconciled_source_event(" in module_text
    assert "clear_deferred_gap(" in module_text
    assert "reconcile_replay_policy.decide_comment_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_submitted_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_dismissed_replay_plan(" in module_text
