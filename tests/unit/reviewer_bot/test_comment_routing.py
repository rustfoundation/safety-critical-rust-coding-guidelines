from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import comment_application, comment_routing, review_state
from scripts.reviewer_bot_lib.context import CommentEventRequest
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state


def test_record_conversation_freshness_returns_true_when_only_reviewer_activity_changes(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    assert harness.handlers is harness.runtime.handlers
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    review_state.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T09:00:00Z",
        actor="alice",
    )
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_id=100,
        comment_author="alice",
        comment_body="hello",
        comment_created_at="2026-03-17T10:00:00Z",
        comment_source_event_key="issue_comment:100",
    )

    changed = comment_application.record_conversation_freshness(
        harness.runtime,
        state,
        request,
    )

    assert changed is True
    assert review["last_reviewer_activity"] == "2026-03-17T10:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMMENT_USER_TYPE": "Bot", "COMMENT_AUTHOR": "reviewer-bot"}, "bot_account"),
        ({"COMMENT_INSTALLATION_ID": "12345"}, "github_app_or_other_automation"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice"}, "repo_user_principal"),
        ({"COMMENT_AUTHOR": "mystery", "COMMENT_USER_TYPE": ""}, "unknown_actor"),
    ],
)
def test_classify_issue_comment_actor(monkeypatch, env, expected):
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        comment_author=env.get("COMMENT_AUTHOR", ""),
        comment_body="hello",
        comment_user_type=env.get("COMMENT_USER_TYPE", ""),
    )
    request = CommentEventRequest(
        **{
            **request.__dict__,
            "comment_installation_id": env.get("COMMENT_INSTALLATION_ID", ""),
        }
    )
    assert comment_routing.classify_issue_comment_actor(request) == expected


def test_classify_comment_payload_distinguishes_command_plus_text():
    payload = comment_routing.classify_comment_payload(
        SimpleNamespace(
            BOT_MENTION="@guidelines-bot",
            adapters=SimpleNamespace(
                commands=SimpleNamespace(
                    strip_code_blocks=lambda body: body,
                    parse_command=lambda body: ("queue", []),
                )
            ),
        ),
        "hello\n@guidelines-bot /queue",
    )
    assert payload["comment_class"] == "command_plus_text"
    assert payload["has_non_command_text"] is True


def test_route_issue_comment_trust_allows_only_same_repo_repo_user_principal(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="carol",
        comment_author="alice",
        comment_body="hello",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        github_ref="refs/heads/main",
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="carol",
    )
    assert comment_routing.route_issue_comment_trust(harness.runtime, 42, request, trust_context) == "pr_trusted_direct"


def test_route_issue_comment_trust_fails_closed_for_ambiguous_same_repo(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="carol",
        comment_author="alice",
        comment_body="hello",
        comment_user_type="",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        github_ref="refs/heads/main",
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="carol",
    )
    with pytest.raises(RuntimeError, match="Ambiguous same-repo PR comment trust posture"):
        comment_routing.route_issue_comment_trust(harness.runtime, 42, request, trust_context)


def test_build_pr_comment_observer_payload_wrapper_uses_explicit_env_facts(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    harness.wrapper_apply_inputs(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="@guidelines-bot /queue",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        github_ref="refs/heads/main",
    )
    harness.config.set("GITHUB_RUN_ID", 777)
    harness.config.set("GITHUB_RUN_ATTEMPT", 2)
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_author="dana",
    )

    payload = harness.build_observer_payload(42)

    assert payload["kind"] == "observer_noop"
    assert payload["reason"] == "trusted_direct_same_repo_human_comment"
    assert payload["source_run_id"] == 777
    assert payload["source_run_attempt"] == 2
    assert payload["pr_number"] == 42


def test_build_pr_comment_observer_payload_uses_same_comment_classification_as_payload_parser(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello\n@guidelines-bot /queue",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        github_ref="refs/heads/main",
        github_run_id=777,
        github_run_attempt=2,
    )
    harness.add_pull_request_metadata(
        issue_number=42,
        head_repo_full_name="fork/example",
        pr_author="dana",
    )

    payload = comment_routing.build_pr_comment_observer_payload(
        harness.runtime,
        42,
        request,
        trust_context,
    )

    assert payload["comment_class"] == "command_plus_text"
    assert payload["has_non_command_text"] is True
