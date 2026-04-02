"""Comment payload parsing, trust routing, and direct comment handling."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .context import CommentEventRequest, PrCommentTrustContext
from .event_inputs import (
    build_comment_event_request as decode_comment_event_request,
)
from .event_inputs import (
    build_pr_comment_trust_context as decode_pr_comment_trust_context,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def build_comment_event_request(*, issue_number: int | None = None) -> CommentEventRequest:
    return decode_comment_event_request(issue_number=issue_number)


def build_pr_comment_trust_context() -> PrCommentTrustContext:
    return decode_pr_comment_trust_context()


def _require_v18_for_pr(state: dict, request: CommentEventRequest, context: str) -> bool:
    if not request.is_pull_request:
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        print(f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True


def _normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def _digest_body(body: str) -> str:
    return hashlib.sha256(_normalize_comment_body(body).encode("utf-8")).hexdigest()


def _comment_line_is_command(bot, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    pattern = rf"^{re.escape(bot.BOT_MENTION)}\s+/[A-Za-z0-9?_-]+(?:\s+.*)?$"
    return re.match(pattern, stripped) is not None


def classify_comment_payload(bot, body: str) -> dict:
    normalized = _normalize_comment_body(bot.strip_code_blocks(body))
    if not normalized:
        return {
            "comment_class": "empty_or_whitespace",
            "has_non_command_text": False,
            "command_count": 0,
            "command": None,
            "args": [],
            "normalized_body": normalized,
        }
    lines = [line for line in normalized.splitlines() if line.strip()]
    command_lines = [line for line in lines if _comment_line_is_command(bot, line)]
    non_command_lines = [line for line in lines if not _comment_line_is_command(bot, line)]
    parsed = bot.parse_command(normalized)
    command = None
    args: list[str] = []
    if parsed:
        command, args = parsed
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
        "normalized_body": normalized,
    }


def _classify_issue_comment_actor(request: CommentEventRequest) -> str:
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


def classify_issue_comment_actor(request: CommentEventRequest | None = None) -> str:
    return _classify_issue_comment_actor(request or build_comment_event_request())


def _is_self_comment(bot, author: str) -> bool:
    return author.strip().lower() == bot.BOT_NAME.lower() or author.strip().lower() == bot.BOT_MENTION.lstrip("@").lower()


def _fetch_pr_metadata(bot, issue_number: int) -> dict:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch live PR metadata for #{issue_number}")
    if not isinstance(pull_request.get("head"), dict) or not isinstance(pull_request.get("user"), dict):
        raise RuntimeError(f"Unusable PR metadata for #{issue_number}")
    return pull_request


def _classify_pr_comment_processing_target(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> str:
    actor_class = _classify_issue_comment_actor(request)
    if actor_class in {"bot_account", "github_app_or_other_automation"} or _is_self_comment(bot, request.comment_author):
        return "safe_noop"
    pull_request = _fetch_pr_metadata(bot, request.issue_number)
    head_repo = pull_request.get("head", {}).get("repo", {})
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if not isinstance(head_full_name, str) or not head_full_name:
        raise RuntimeError("Missing PR head repository metadata for trust routing")
    is_cross_repo = head_full_name != trust_context.github_repository
    pr_author = pull_request.get("user", {}).get("login")
    is_dependabot_restricted = pr_author == "dependabot[bot]"
    author_association = trust_context.comment_author_association
    trusted_principal = actor_class == "repo_user_principal" and author_association in bot.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
    if is_cross_repo or is_dependabot_restricted:
        return "pr_deferred_reconcile"
    if trusted_principal:
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def classify_pr_comment_processing_target(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = request or build_comment_event_request(issue_number=issue_number)
    return _classify_pr_comment_processing_target(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(),
    )


def _route_issue_comment_trust(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> str:
    if not request.is_pull_request:
        return "issue_direct"
    target = _classify_pr_comment_processing_target(bot, request, trust_context)
    if target != "pr_trusted_direct":
        return target
    workflow_file = trust_context.current_workflow_file
    workflow_ref = trust_context.github_ref
    if workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml" and workflow_ref == "refs/heads/main":
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def route_issue_comment_trust(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> str:
    comment_request = request or build_comment_event_request(issue_number=issue_number)
    return _route_issue_comment_trust(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(),
    )


def _build_pr_comment_observer_payload(
    bot,
    request: CommentEventRequest,
    trust_context: PrCommentTrustContext,
) -> dict:
    actor_class = _classify_issue_comment_actor(request)
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
    if actor_class in {"bot_account", "github_app_or_other_automation"} or _is_self_comment(bot, request.comment_author):
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "ignored_non_human_automation",
            **base_payload,
        }
    processing_target = _classify_pr_comment_processing_target(bot, request, trust_context)
    if processing_target == "pr_trusted_direct":
        return {
            "schema_version": 1,
            "kind": "observer_noop",
            "reason": "trusted_direct_same_repo_human_comment",
            **base_payload,
        }
    body = request.comment_body
    normalized = _normalize_comment_body(body)
    command_pattern = re.compile(r"^@guidelines\-bot\s+/[A-Za-z0-9?_\-]+(?:\s+.*)?$")
    lines = [line for line in normalized.splitlines() if line.strip()]
    command_lines = [line for line in lines if command_pattern.match(line.strip())]
    non_command_lines = [line for line in lines if not command_pattern.match(line.strip())]
    if not normalized:
        comment_class = "empty_or_whitespace"
    elif command_lines and not non_command_lines:
        comment_class = "command_only"
    elif command_lines and non_command_lines:
        comment_class = "command_plus_text"
    else:
        comment_class = "plain_text"
    return {
        "schema_version": 2,
        **base_payload,
        "comment_id": comment_id,
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "source_body_digest": _digest_body(body),
        "source_created_at": request.comment_created_at,
        "actor_login": request.comment_author,
        "actor_id": request.comment_author_id,
        "actor_class": "repo_user_principal" if actor_class == "repo_user_principal" else "unknown_actor",
        "source_artifact_name": (
            f"reviewer-bot-comment-context-{trust_context.github_run_id}-attempt-"
            f"{trust_context.github_run_attempt}"
        ),
    }


def build_pr_comment_observer_payload(
    bot,
    issue_number: int,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> dict:
    comment_request = request or build_comment_event_request(issue_number=issue_number)
    return _build_pr_comment_observer_payload(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(),
    )


def _record_conversation_freshness(
    bot,
    state: dict,
    request: CommentEventRequest,
) -> bool:
    issue_number = request.issue_number
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    comment_author = request.comment_author
    created_at = request.comment_created_at
    semantic_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if request.issue_author and request.issue_author.lower() == comment_author.lower():
        return bot.reviews_module.accept_channel_event(
            review_data,
            "contributor_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
    current_reviewer = review_data.get("current_reviewer")
    if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():
        changed = bot.reviews_module.accept_channel_event(
            review_data,
            "reviewer_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
        previous_activity = review_data.get("last_reviewer_activity")
        previous_warning = review_data.get("transition_warning_sent")
        previous_notice = review_data.get("transition_notice_sent_at")
        bot.reviews_module.record_reviewer_activity(review_data, created_at)
        activity_changed = (
            previous_activity != review_data.get("last_reviewer_activity")
            or previous_warning != review_data.get("transition_warning_sent")
            or previous_notice != review_data.get("transition_notice_sent_at")
        )
        return changed or activity_changed
    return False


def _store_pending_privileged_command(review_data: dict, issue_number: int, source_event_key: str, command_name: str, actor: str, args: list[str]) -> bool:
    pending = review_data.setdefault("pending_privileged_commands", {})
    pending[source_event_key] = {
        "source_event_key": source_event_key,
        "command_name": command_name,
        "issue_number": issue_number,
        "actor": actor,
        "args": args,
        "status": "pending",
        "created_at": _now_iso(),
    }
    return True


def _validate_accept_no_fls_changes_handoff(
    bot,
    request: CommentEventRequest,
) -> tuple[bool, dict]:
    if request.is_pull_request:
        return False, {"reason": "pull_request_target_not_allowed"}
    labels = bot.parse_issue_labels()
    if bot.FLS_AUDIT_LABEL not in labels:
        return False, {"reason": "missing_fls_audit_label"}
    permission_status = bot.get_user_permission_status(request.comment_author, "triage")
    if permission_status == "unavailable":
        return False, {"reason": "authorization_unavailable"}
    if permission_status != "granted":
        return False, {"reason": "authorization_failed"}
    return True, {
        "command_name": "accept-no-fls-changes",
        "issue_number": request.issue_number,
        "actor": request.comment_author,
        "authorization": {"required_permission": "triage", "authorized": True},
        "target": {"kind": "issue", "number": request.issue_number, "labels": sorted(labels)},
    }


def _handle_command(
    bot,
    state: dict,
    request: CommentEventRequest,
    classified: dict,
) -> bool:
    if not isinstance(classified, dict):
        return False
    issue_number = request.issue_number
    comment_author = request.comment_author
    command = classified.get("command")
    args = classified.get("args") or []
    if not isinstance(command, str):
        return False
    actor_class = _classify_issue_comment_actor(request)
    if actor_class in {"unknown_actor", "bot_account", "github_app_or_other_automation"}:
        return False
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    source_event_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if command == "accept-no-fls-changes":
        is_valid, metadata = _validate_accept_no_fls_changes_handoff(bot, request)
        if not is_valid:
            bot.post_comment(
                issue_number,
                "❌ This command is not eligible for privileged handoff from the current trusted live state.",
            )
            return False
        stored = _store_pending_privileged_command(review_data, issue_number, source_event_key, command, comment_author, list(args))
        if stored:
            review_data["pending_privileged_commands"][source_event_key].update(metadata)
            bot.post_comment(
                issue_number,
                "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
            )
        return stored
    if command == "_multiple_commands":
        bot.post_comment(issue_number, f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. For a list of commands, use `{bot.BOT_MENTION} /commands`.")
        return False
    response = ""
    success = False
    state_changed = False
    if command == "pass":
        response, success = bot.handle_pass_command(state, issue_number, comment_author, " ".join(args) if args else None)
        state_changed = success
    elif command == "away":
        if args:
            response, success = bot.handle_pass_until_command(state, issue_number, comment_author, args[0], " ".join(args[1:]) if len(args) > 1 else None)
            state_changed = success
        else:
            response = f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`"
    elif command == "label":
        response, success, state_changed = bot.handle_label_command(state, issue_number, " ".join(args))
    elif command == "sync-members":
        response, success = bot.handle_sync_members_command(state)
        state_changed = success
    elif command == "queue":
        response, success = bot.handle_queue_command(state)
    elif command == "commands":
        response, success = bot.handle_commands_command()
    elif command == "claim":
        response, success = bot.handle_claim_command(state, issue_number, comment_author)
        state_changed = success
    elif command == "release":
        response, success = bot.handle_release_command(state, issue_number, comment_author, list(args))
        state_changed = success
    elif command == "rectify":
        response, success, state_changed = bot.handle_rectify_command(state, issue_number, comment_author)
    elif command == "r?-user":
        response, success = bot.handle_assign_command(state, issue_number, args[0] if args else "")
        state_changed = success
    elif command == "assign-from-queue":
        response, success = bot.handle_assign_from_queue_command(state, issue_number)
        state_changed = success
    elif command == "r?":
        response = f"❌ Missing target. Usage:\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Assign next reviewer from queue"
    elif command == "_malformed_known":
        attempted = args[0] if args else "command"
        response = f"⚠️ Did you mean `{bot.BOT_MENTION} /{attempted}`?\n\nCommands require a `/` prefix."
    elif command == "_malformed_unknown":
        attempted = args[0] if args else ""
        response = f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\nTry `{bot.BOT_MENTION} /commands` to see available commands."
    else:
        response = f"❌ Unknown command: `/{command}`\n\nAvailable commands:\n{bot.get_commands_help()}"
    comment_id = request.comment_id
    if comment_id > 0 and command != "_multiple_commands":
        bot.add_reaction(comment_id, "eyes")
        if success:
            bot.add_reaction(comment_id, "+1")
    if response:
        bot.post_comment(issue_number, response)
    return state_changed


def _process_comment_event(bot, state: dict, request: CommentEventRequest) -> bool:
    comment_id = request.comment_id
    comment_created_at = request.comment_created_at or _now_iso()
    comment_request = CommentEventRequest(
        **{**request.__dict__, "comment_created_at": comment_created_at}
    )
    classified = classify_comment_payload(bot, comment_request.comment_body)
    comment_class = classified["comment_class"]
    state_changed = False
    if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:
        state_changed = _record_conversation_freshness(bot, state, comment_request) or state_changed
    if comment_class in {"command_only", "command_plus_text"} and int(classified.get("command_count", 0)) == 1:
        state_changed = _handle_command(bot, state, comment_request, classified) or state_changed
    return state_changed


def handle_comment_event(
    bot,
    state: dict,
    request: CommentEventRequest | None = None,
    trust_context: PrCommentTrustContext | None = None,
) -> bool:
    bot.assert_lock_held("handle_comment_event")
    comment_request = request or build_comment_event_request()
    issue_number = comment_request.issue_number
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    route = _route_issue_comment_trust(
        bot,
        comment_request,
        trust_context or build_pr_comment_trust_context(),
    )
    if route == "safe_noop":
        return False
    if route == "issue_direct":
        if comment_request.issue_state == "closed":
            removed = state.get("active_reviews", {}).pop(str(issue_number), None)
            print(f"Ignoring direct comment on closed issue #{issue_number}")
            return removed is not None
        return _process_comment_event(bot, state, comment_request)
    if route == "pr_trusted_direct":
        if not _require_v18_for_pr(state, comment_request, "pr_trusted_direct_comment"):
            return False
        return _process_comment_event(bot, state, comment_request)
    raise RuntimeError("Deferred PR comment events must not mutate directly in trusted workflows")
