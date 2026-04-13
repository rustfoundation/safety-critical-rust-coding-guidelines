import pytest

pytestmark = pytest.mark.integration

from scripts.reviewer_bot_lib import comment_routing, reconcile, review_state
from scripts.reviewer_bot_lib.config import FLS_AUDIT_LABEL
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state


def test_handle_non_pr_issue_comment_creates_pending_privileged_command(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    entry = review_state.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        issue_labels=(FLS_AUDIT_LABEL,),
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    effects = harness.capture_comment_side_effects()
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"

    assert comment_routing.handle_comment_event(harness.runtime, state, request) is True
    pending = state["active_reviews"]["42"]["sidecars"]["pending_privileged_commands"]
    assert pending["issue_comment:100"]["command_name"] == "accept-no-fls-changes"
    assert effects.comments == [
        (
            42,
            "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. "
            "Use the isolated privileged workflow to execute it from issue `the configured state issue` state.",
        )
    ]
    assert effects.reactions == []

def test_closed_non_pr_plain_text_comment_does_not_create_review_entry(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert comment_routing.handle_comment_event(harness.runtime, state, request) is False
    assert state["active_reviews"] == {}

def test_closed_non_pr_command_comment_does_not_create_pending_privileged_command(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    effects = harness.capture_comment_side_effects()
    harness.runtime.set_config_value("ISSUE_LABELS", f'["{FLS_AUDIT_LABEL}"]')
    harness.runtime.github.check_user_permission = lambda username, required_permission="triage": True

    assert comment_routing.handle_comment_event(harness.runtime, state, request) is False
    assert state["active_reviews"] == {}
    assert effects.comments == []

def test_closed_non_pr_comment_removes_stale_review_entry(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert comment_routing.handle_comment_event(harness.runtime, state, request) is True
    assert "42" not in state["active_reviews"]

def test_closed_non_pr_comment_without_entry_returns_false(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="closed",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: close comment",
    )

    assert comment_routing.handle_comment_event(harness.runtime, state, request) is False
    assert state["active_reviews"] == {}

def test_open_non_pr_plain_text_comment_still_updates_freshness(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_state="open",
        issue_author="dana",
        comment_author="dana",
        comment_body="reviewer-bot validation: contributor plain text comment",
    )

    assert harness.handle_comment_event(state, request=request) is True
    accepted = state["active_reviews"]["42"]["contributor_comment"]["accepted"]
    assert accepted["semantic_key"] == "issue_comment:100"

def test_observer_noop_payload_is_safe_noop(tmp_path, monkeypatch):
    state = make_state()
    harness = CommentRoutingHarness(monkeypatch)
    review_state.ensure_review_entry(state, 42, create=True)
    harness.runtime.stub_deferred_payload(
        {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "ignored_non_human_automation",
            "source_workflow_name": "Reviewer Bot PR Comment Observer",
            "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "source_run_id": 777,
            "source_run_attempt": 1,
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "source_event_key": "issue_comment:111",
            "pr_number": 42,
        }
    )
    harness.config.set("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    harness.config.set("WORKFLOW_RUN_TRIGGERING_ID", "777")
    harness.config.set("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    harness.config.set("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    assert reconcile.handle_workflow_run_event_result(harness.runtime, state).state_changed is False
    assert state["active_reviews"]["42"]["sidecars"]["deferred_gaps"] == {}


def test_cross_repo_pr_comment_route_remains_deferred_not_direct(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello",
    )
    trust_context = harness.trust_context(
        route_outcome=comment_routing.comment_routing_policy.PrCommentRouterOutcome.DEFERRED_RECONCILE,
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_head_full_name="fork/example",
        pr_author="dana",
    )

    with pytest.raises(RuntimeError, match="Deferred PR comment events must not mutate directly"):
        comment_routing.handle_comment_event(harness.runtime, state, request, trust_context)
