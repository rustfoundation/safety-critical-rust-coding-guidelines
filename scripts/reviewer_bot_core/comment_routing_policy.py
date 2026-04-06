"""Trust-routing and comment-payload classification owner.

Future changes that belong here:
- issue-comment actor classification
- PR comment route classification and trust posture outcomes
- observer payload field selection from already-fetched routing facts
- comment payload class derivation from already-parsed command facts

Future changes that do not belong here:
- command decision or command side-effect planning
- live GitHub reads, workflow/artifact downloads, or state mutation
- direct comment processing and GitHub writes

Old module no longer the preferred place for these changes:
- `scripts/reviewer_bot_lib/comment_routing.py`
"""

from __future__ import annotations

import re


def classify_issue_comment_actor(request) -> str:
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


def comment_line_is_command(bot_mention: str, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    pattern = rf"^{re.escape(bot_mention)}\s+/[A-Za-z0-9?_-]+(?:\s+.*)?$"
    return re.match(pattern, stripped) is not None


def classify_comment_payload(bot_mention: str, normalized_body: str, parsed_command) -> dict:
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
    command_lines = [line for line in lines if comment_line_is_command(bot_mention, line)]
    non_command_lines = [line for line in lines if not comment_line_is_command(bot_mention, line)]
    command = None
    args: list[str] = []
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


def classify_pr_comment_processing_target(
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


def route_issue_comment_trust(request, trust_context, *, processing_target: str | None = None) -> str:
    if not request.is_pull_request:
        return "issue_direct"
    target = processing_target
    if target != "pr_trusted_direct":
        return target or "safe_noop"
    workflow_file = trust_context.current_workflow_file
    workflow_ref = trust_context.github_ref
    if workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml" and workflow_ref == "refs/heads/main":
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def build_pr_comment_observer_payload(
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
