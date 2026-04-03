"""Comment mutation and replay application helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .context import AssignmentRequest, CommentEventRequest
from .review_state import (
    accept_channel_event,
    ensure_review_entry,
    record_reviewer_activity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def digest_comment_body(body: str) -> str:
    return hashlib.sha256(normalize_comment_body(body).encode("utf-8")).hexdigest()


def record_conversation_freshness(
    bot,
    state: dict,
    request: CommentEventRequest,
) -> bool:
    issue_number = request.issue_number
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    comment_author = request.comment_author
    created_at = request.comment_created_at
    semantic_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if request.issue_author and request.issue_author.lower() == comment_author.lower():
        return accept_channel_event(
            review_data,
            "contributor_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
    current_reviewer = review_data.get("current_reviewer")
    if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():
        changed = accept_channel_event(
            review_data,
            "reviewer_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
        previous_activity = review_data.get("last_reviewer_activity")
        previous_warning = review_data.get("transition_warning_sent")
        previous_notice = review_data.get("transition_notice_sent_at")
        record_reviewer_activity(review_data, created_at)
        activity_changed = (
            previous_activity != review_data.get("last_reviewer_activity")
            or previous_warning != review_data.get("transition_warning_sent")
            or previous_notice != review_data.get("transition_notice_sent_at")
        )
        return changed or activity_changed
    return False


def store_pending_privileged_command(review_data: dict, issue_number: int, source_event_key: str, command_name: str, actor: str, args: list[str]) -> bool:
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


def build_assignment_request_from_comment(request: CommentEventRequest) -> AssignmentRequest:
    return AssignmentRequest(
        issue_number=request.issue_number,
        issue_author=request.issue_author,
        is_pull_request=request.is_pull_request,
    )


def validate_accept_no_fls_changes_handoff(
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


def apply_comment_command(
    bot,
    state: dict,
    request: CommentEventRequest,
    classified: dict,
    *,
    classify_issue_comment_actor,
) -> bool:
    if not isinstance(classified, dict):
        return False
    issue_number = request.issue_number
    comment_author = request.comment_author
    command = classified.get("command")
    args = classified.get("args") or []
    if not isinstance(command, str):
        return False
    actor_class = classify_issue_comment_actor(request)
    if actor_class in {"unknown_actor", "bot_account", "github_app_or_other_automation"}:
        return False
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    source_event_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if command == "accept-no-fls-changes":
        is_valid, metadata = validate_accept_no_fls_changes_handoff(bot, request)
        if not is_valid:
            bot.post_comment(
                issue_number,
                "❌ This command is not eligible for privileged handoff from the current trusted live state.",
            )
            return False
        stored = store_pending_privileged_command(review_data, issue_number, source_event_key, command, comment_author, list(args))
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
    assignment_request = build_assignment_request_from_comment(request)
    if command == "pass":
        response, success = bot.handle_pass_command(
            state,
            issue_number,
            comment_author,
            " ".join(args) if args else None,
            request=assignment_request,
        )
        state_changed = success
    elif command == "away":
        if args:
            response, success = bot.handle_pass_until_command(
                state,
                issue_number,
                comment_author,
                args[0],
                " ".join(args[1:]) if len(args) > 1 else None,
                request=assignment_request,
            )
            state_changed = success
        else:
            response = f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`"
    elif command == "label":
        response, success, state_changed = bot.handle_label_command(
            state,
            issue_number,
            " ".join(args),
            request=assignment_request,
        )
    elif command == "sync-members":
        response, success = bot.handle_sync_members_command(state)
        state_changed = success
    elif command == "queue":
        response, success = bot.handle_queue_command(state)
    elif command == "commands":
        response, success = bot.handle_commands_command()
    elif command == "claim":
        response, success = bot.handle_claim_command(
            state,
            issue_number,
            comment_author,
            request=assignment_request,
        )
        state_changed = success
    elif command == "release":
        response, success = bot.handle_release_command(
            state,
            issue_number,
            comment_author,
            list(args),
            request=assignment_request,
        )
        state_changed = success
    elif command == "rectify":
        response, success, state_changed = bot.handle_rectify_command(state, issue_number, comment_author)
    elif command == "r?-user":
        response, success = bot.handle_assign_command(
            state,
            issue_number,
            args[0] if args else "",
            request=assignment_request,
        )
        state_changed = success
    elif command == "assign-from-queue":
        response, success = bot.handle_assign_from_queue_command(
            state,
            issue_number,
            request=assignment_request,
        )
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


def process_comment_event(
    bot,
    state: dict,
    request: CommentEventRequest,
    *,
    classify_comment_payload,
    classify_issue_comment_actor,
) -> bool:
    comment_id = request.comment_id
    comment_created_at = request.comment_created_at or _now_iso()
    comment_request = CommentEventRequest(**{**request.__dict__, "comment_created_at": comment_created_at})
    classified = classify_comment_payload(bot, comment_request.comment_body)
    comment_class = classified["comment_class"]
    state_changed = False
    if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:
        state_changed = record_conversation_freshness(bot, state, comment_request) or state_changed
    if comment_class in {"command_only", "command_plus_text"} and int(classified.get("command_count", 0)) == 1:
        state_changed = apply_comment_command(
            bot,
            state,
            comment_request,
            classified,
            classify_issue_comment_actor=classify_issue_comment_actor,
        ) or state_changed
    return state_changed
