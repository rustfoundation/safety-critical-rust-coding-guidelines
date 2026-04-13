import pytest

from scripts.reviewer_bot_lib import reconcile
from tests.fixtures.reconcile_harness import (
    ReconcileHarness,
    issue_comment_payload,
    review_comment_payload,
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
    assert "pull_request_review:11" not in _deferred_gaps(review)


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


def test_handle_workflow_run_event_treats_observer_noop_payload_as_no_mutation(monkeypatch):
    state = make_state(epoch="freshness_v15")
    harness = ReconcileHarness(
        monkeypatch,
        {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "trusted_direct_same_repo_human_comment",
            "source_workflow_name": "Reviewer Bot PR Comment Observer",
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "source_run_id": 900,
            "source_run_attempt": 1,
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "source_event_key": "issue_comment:210",
            "pr_number": 42,
        },
    )

    result = reconcile.handle_workflow_run_event_result(harness.runtime, state)

    assert result.state_changed is False
    assert result.touched_items == [42]
    assert harness.runtime.drain_touched_items() == []
    assert state["active_reviews"]["42"]["sidecars"]["reconciled_source_events"] == {}


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
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_request_failure(
        endpoint="issues/comments/99",
        status_code=404,
        payload={"message": "missing"},
        failure_kind="not_found",
    )

    assert harness.run(state) is True
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"]["semantic_key"] == "issue_comment:99"
    assert state["active_reviews"]["42"]["sidecars"]["deferred_gaps"]["issue_comment:99"]["reason"] == "reconcile_failed_closed"


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
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
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


def test_deferred_review_comment_reconcile_records_reviewer_freshness(monkeypatch):
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
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_review_comment(
        comment_id=302,
        body=live_body,
        author="alice",
        author_type="User",
        author_association="MEMBER",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:302"


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
        ),
    )
    harness.add_pull_request(pr_number=42, author="dana")
    harness.add_request_failure(
        endpoint="pulls/comments/303",
        status_code=404,
        payload={"message": "missing"},
        failure_kind="not_found",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    assert harness.run(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:303"
    assert _deferred_gaps(review)["pull_request_review_comment:303"]["reason"] == "reconcile_failed_closed"


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
    assert "reconcile_replay_policy.decide_review_dismissed_replay(" in module_text


def test_d2_reconcile_replay_path_stays_decode_read_apply_orchestration_only():
    with open("scripts/reviewer_bot_lib/reconcile.py", encoding="utf-8") as handle:
        module_text = handle.read()

    assert "build_deferred_comment_replay_context(" in module_text
    assert "_read_live_comment_replay_context(" in module_text
    assert "process_comment_event(" in module_text
    assert "record_conversation_freshness(" in module_text
    assert "_mark_reconciled_source_event(" in module_text
    assert "_clear_source_event_key(" in module_text
    assert "reconcile_replay_policy.decide_comment_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_submitted_replay(" in module_text
    assert "reconcile_replay_policy.decide_review_dismissed_replay(" in module_text
