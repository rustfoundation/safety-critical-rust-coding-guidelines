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


def _legacy_classify_pr_comment_processing_target(
    request,
    trust_context,
    *,
    actor_class: str,
    is_self_comment: bool,
    pr_head_full_name: str | None,
    pr_author: str | None,
    author_association_trust_allowlist,
) -> str:
    if actor_class in {"bot_account", "github_app_or_other_automation"} or is_self_comment:
        return "safe_noop"
    if not isinstance(pr_head_full_name, str) or not pr_head_full_name:
        raise RuntimeError("Missing PR head repository metadata for trust routing")
    is_cross_repo = pr_head_full_name != trust_context.github_repository
    is_dependabot_restricted = pr_author == "dependabot[bot]"
    author_association = trust_context.comment_author_association
    trusted_principal = actor_class == "repo_user_principal" and author_association in author_association_trust_allowlist
    if is_cross_repo or is_dependabot_restricted:
        return "pr_deferred_reconcile"
    if trusted_principal:
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def _legacy_route_issue_comment_trust(request, trust_context, *, processing_target: str | None = None) -> str:
    if not request.is_pull_request:
        return "issue_direct"
    target = processing_target
    if target != "pr_trusted_direct":
        return target or "safe_noop"
    if (
        trust_context.current_workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml"
        and trust_context.github_ref == "refs/heads/main"
    ):
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def _legacy_build_pr_comment_observer_payload(
    request,
    trust_context,
    *,
    actor_class: str,
    processing_target: str,
    payload_classification: dict,
    body_digest: str,
) -> dict:
    comment_id = request.comment_id
    base_payload = {
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": trust_context.github_run_id,
        "source_run_attempt": trust_context.github_run_attempt,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": f"issue_comment:{comment_id}",
        "pr_number": request.issue_number,
    }
    if actor_class in {"bot_account", "github_app_or_other_automation"}:
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "ignored_non_human_automation",
            **base_payload,
        }
    if processing_target == "pr_trusted_direct":
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "trusted_direct_same_repo_human_comment",
            **base_payload,
        }
    return {
        "schema_version": 2,
        **base_payload,
        "comment_id": comment_id,
        "comment_class": payload_classification["comment_class"],
        "has_non_command_text": payload_classification["has_non_command_text"],
        "source_body_digest": body_digest,
        "source_created_at": request.comment_created_at,
        "actor_login": request.comment_author,
        "actor_id": request.comment_author_id,
        "actor_class": "repo_user_principal" if actor_class == "repo_user_principal" else "unknown_actor",
        "source_artifact_name": (
            f"reviewer-bot-comment-context-{trust_context.github_run_id}-attempt-"
            f"{trust_context.github_run_attempt}"
        ),
    }


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
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                comment_author_association="MEMBER",
                current_workflow_file=".github/workflows/reviewer-bot-pr-comment-trusted.yml",
                github_ref="refs/heads/main",
            ),
            "head_repo_full_name": "rustfoundation/safety-critical-rust-coding-guidelines",
            "pr_author": "carol",
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
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                comment_author_association="MEMBER",
                current_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
                github_ref="refs/heads/main",
            ),
            "head_repo_full_name": "fork/example",
            "pr_author": "carol",
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
                github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
                comment_author_association="NONE",
                current_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
                github_ref="refs/heads/main",
            ),
            "head_repo_full_name": "rustfoundation/safety-critical-rust-coding-guidelines",
            "pr_author": "carol",
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
                comment_author_association="MEMBER",
                current_workflow_file=".github/workflows/reviewer-bot-issue-comment-direct.yml",
                github_ref="refs/heads/main",
            ),
            "head_repo_full_name": None,
            "pr_author": None,
        },
    ]

    assert fixture["route_scenarios"] == [scenario["name"] for scenario in scenarios]

    for scenario in scenarios:
        actor_class = comment_routing_policy.classify_issue_comment_actor(scenario["request"])
        legacy_target = None
        new_target = None
        if scenario["request"].is_pull_request:
            legacy_target = _legacy_classify_pr_comment_processing_target(
                scenario["request"],
                scenario["trust_context"],
                actor_class=actor_class,
                is_self_comment=False,
                pr_head_full_name=scenario["head_repo_full_name"],
                pr_author=scenario["pr_author"],
                author_association_trust_allowlist=harness.runtime.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
            )
            new_target = comment_routing_policy.classify_pr_comment_processing_target(
                scenario["request"],
                scenario["trust_context"],
                actor_class=actor_class,
                is_self_comment=False,
                pr_head_full_name=scenario["head_repo_full_name"],
                pr_author=scenario["pr_author"],
                author_association_trust_allowlist=harness.runtime.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
            )
            assert new_target == legacy_target

        assert comment_routing_policy.route_issue_comment_trust(
            scenario["request"],
            scenario["trust_context"],
            processing_target=new_target,
        ) == _legacy_route_issue_comment_trust(
            scenario["request"],
            scenario["trust_context"],
            processing_target=legacy_target,
        )


def test_observer_payload_equivalence_matches_legacy_helper_outcomes(monkeypatch):
    fixture = _load_fixture()
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=True,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello\n@guidelines-bot /queue",
        comment_user_type="User",
    )
    trust_context = harness.trust_context(
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        comment_author_association="MEMBER",
        current_workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
        github_ref="refs/heads/main",
        github_run_id=777,
        github_run_attempt=2,
    )
    normalized = "hello\n@guidelines-bot /queue"
    parsed = ("queue", [])
    payload_classification = _legacy_classify_comment_payload(harness.runtime.BOT_MENTION, normalized, parsed)
    actor_class = _legacy_classify_issue_comment_actor(request)
    processing_target = _legacy_classify_pr_comment_processing_target(
        request,
        trust_context,
        actor_class=actor_class,
        is_self_comment=False,
        pr_head_full_name="fork/example",
        pr_author="dana",
        author_association_trust_allowlist=harness.runtime.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
    )

    assert "deferred_observer_payload" in fixture["payload_scenarios"]
    assert comment_routing_policy.build_pr_comment_observer_payload(
        request,
        trust_context,
        actor_class=actor_class,
        processing_target=processing_target,
        payload_classification=payload_classification,
        body_digest=comment_routing.digest_comment_body(request.comment_body),
    ) == _legacy_build_pr_comment_observer_payload(
        request,
        trust_context,
        actor_class=actor_class,
        processing_target=processing_target,
        payload_classification=payload_classification,
        body_digest=comment_routing.digest_comment_body(request.comment_body),
    )
