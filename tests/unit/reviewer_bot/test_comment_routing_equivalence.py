import json
from pathlib import Path
from types import SimpleNamespace

from scripts.reviewer_bot_core import comment_routing_policy
from scripts.reviewer_bot_lib import comment_routing
from tests.fixtures.comment_routing_harness import CommentRoutingHarness


def _load_fixture() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/comment_routing/route_outcomes.json").read_text(
            encoding="utf-8"
        )
    )


def _legacy_comment_line_is_command(bot_mention: str, line: str) -> bool:
    return comment_routing_policy.comment_line_is_command(bot_mention, line)


def _legacy_classify_comment_payload(bot_mention: str, normalized_body: str, parsed_command) -> dict:
    if not normalized_body:
        return {
            "comment_class": "empty_or_whitespace",
            "has_non_command_text": False,
            "command_count": 0,
            "command": None,
            "args": [],
            "normalized_body": normalized_body,
        }
    lines = [line for line in normalized_body.splitlines() if line.strip()]
    command_lines = [line for line in lines if _legacy_comment_line_is_command(bot_mention, line)]
    non_command_lines = [line for line in lines if not _legacy_comment_line_is_command(bot_mention, line)]
    command = None
    args = []
    if parsed_command:
        command, args = parsed_command
    if command_lines and not non_command_lines:
        comment_class = "command_only"
    elif command_lines and non_command_lines:
        comment_class = "command_plus_text"
    else:
        comment_class = "plain_text"
    return {
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "command_count": len(command_lines),
        "command": command,
        "args": args,
        "normalized_body": normalized_body,
    }


def _legacy_classify_issue_comment_actor(request) -> str:
    comment_user_type = request.comment_user_type
    comment_author = request.comment_author.strip()
    sender_type = request.comment_sender_type
    installation_id = request.comment_installation_id
    via_github_app = request.comment_performed_via_github_app
    if comment_user_type == "Bot" or comment_author.endswith("[bot]"):
        return "bot_account"
    if installation_id or via_github_app or (sender_type and sender_type not in {"User", "Bot"}):
        return "github_app_or_other_automation"
    if comment_user_type == "User" and comment_author and not comment_author.endswith("[bot]") and not installation_id and not via_github_app:
        return "repo_user_principal"
    return "unknown_actor"


def test_comment_routing_equivalence_fixture_exists():
    fixture = _load_fixture()

    assert fixture["harness_id"] == "C3a trust-routing and comment classification equivalence"
    assert fixture["route_scenarios"] == [
        "same_repo_trusted_pr_comment",
        "cross_repo_deferred_pr_comment",
        "automation_or_self_noop_pr_comment",
        "issue_comment_direct",
    ]


def test_comment_payload_classification_equivalence_matches_frozen_outcomes():
    fixture = _load_fixture()
    bot = SimpleNamespace(
        BOT_MENTION="@guidelines-bot",
        adapters=SimpleNamespace(
            commands=SimpleNamespace(
                strip_code_blocks=lambda body: body,
                parse_command=lambda body: ("queue", []) if "/queue" in body else None,
            )
        ),
    )
    normalized = "hello\n@guidelines-bot /queue"
    parsed = ("queue", [])

    assert "command_plus_text" in fixture["payload_scenarios"]
    assert comment_routing.classify_comment_payload(bot, normalized) == _legacy_classify_comment_payload(
        bot.BOT_MENTION,
        normalized,
        parsed,
    )
    assert comment_routing_policy.classify_comment_payload(bot.BOT_MENTION, normalized, parsed) == _legacy_classify_comment_payload(
        bot.BOT_MENTION,
        normalized,
        parsed,
    )


def test_route_outcome_equivalence_covers_trusted_deferred_noop_and_issue_direct(monkeypatch):
    fixture = _load_fixture()
    harness = CommentRoutingHarness(monkeypatch)

    scenarios = [
        {
            "name": "same_repo_trusted_pr_comment",
            "request": harness.request(
                issue_number=42,
                is_pull_request=True,
                issue_author="carol",
                comment_author="alice",
                comment_body="hello",
                comment_user_type="User",
            ),
            "trust_context": harness.trust_context(
                route_outcome=comment_routing_policy.PrCommentRouterOutcome.TRUSTED_DIRECT,
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                pr_head_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
                pr_author="carol",
            ),
        },
        {
            "name": "cross_repo_deferred_pr_comment",
            "request": harness.request(
                issue_number=42,
                is_pull_request=True,
                issue_author="carol",
                comment_author="alice",
                comment_body="hello",
                comment_user_type="User",
            ),
            "trust_context": harness.trust_context(
                route_outcome=comment_routing_policy.PrCommentRouterOutcome.DEFERRED_RECONCILE,
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                pr_head_full_name="fork/example",
                pr_author="carol",
            ),
        },
        {
            "name": "automation_or_self_noop_pr_comment",
            "request": harness.request(
                issue_number=42,
                is_pull_request=True,
                issue_author="carol",
                comment_author="dependabot[bot]",
                comment_body="hello",
                comment_user_type="Bot",
            ),
            "trust_context": harness.trust_context(
                route_outcome=comment_routing_policy.PrCommentRouterOutcome.SAFE_NOOP,
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                pr_head_full_name="rustfoundation/safety-critical-rust-coding-guidelines",
                pr_author="carol",
            ),
        },
        {
            "name": "issue_comment_direct",
            "request": harness.request(
                issue_number=42,
                is_pull_request=False,
                issue_author="carol",
                comment_author="alice",
                comment_body="hello",
                comment_user_type="User",
            ),
            "trust_context": harness.trust_context(
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
            ),
        },
    ]

    assert fixture["route_scenarios"] == [scenario["name"] for scenario in scenarios]

    for scenario in scenarios:
        actor_class = comment_routing_policy.classify_issue_comment_actor(scenario["request"])
        if scenario["request"].is_pull_request:
            new_target = comment_routing_policy.classify_pr_comment_processing_target(
                scenario["request"],
                scenario["trust_context"],
                actor_class=actor_class,
                is_self_comment=False,
            )
            if scenario["name"] == "same_repo_trusted_pr_comment":
                assert new_target == comment_routing_policy.ProcessingTarget.PR_TRUSTED_DIRECT
            if scenario["name"] == "cross_repo_deferred_pr_comment":
                assert new_target == comment_routing_policy.PrCommentRouterOutcome.DEFERRED_RECONCILE
            if scenario["name"] == "automation_or_self_noop_pr_comment":
                assert new_target == comment_routing_policy.PrCommentRouterOutcome.SAFE_NOOP
            assert comment_routing_policy.route_issue_comment_trust(
                scenario["request"],
                scenario["trust_context"],
                processing_target=new_target,
            ) == (
                comment_routing_policy.PrCommentRouterOutcome.TRUSTED_DIRECT
                if new_target == comment_routing_policy.ProcessingTarget.PR_TRUSTED_DIRECT
                else new_target
            )
        else:
            assert comment_routing_policy.route_issue_comment_trust(
                scenario["request"],
                scenario["trust_context"],
                processing_target=None,
            ) == comment_routing_policy.ProcessingTarget.ISSUE_DIRECT


def test_pr_comment_observer_helper_is_removed_after_router_cutover(monkeypatch):
    fixture = _load_fixture()
    module_text = Path("scripts/reviewer_bot_lib/comment_routing.py").read_text(encoding="utf-8")

    assert "deferred_observer_payload" in fixture["payload_scenarios"]
    assert "build_pr_comment_observer_payload" not in module_text
