"""Command decision owner for already-routed comment events.

Future changes that belong here:
- deciding which ordinary command path to invoke from classified comment inputs
- deciding compatibility inline responses for malformed, missing-target, or unknown commands
- deciding whether a classified command remains deferred to legacy privileged handoff handling

Future changes that do not belong here:
- trust routing or comment payload classification
- state mutation, GitHub writes, or reaction/comment side effects
- privileged handoff validation, pending-command shaping, or executor planning

Old module no longer the preferred place for ordinary command-decision changes:
- `scripts/reviewer_bot_lib/comment_application.py`
"""

from __future__ import annotations


def decide_comment_command(bot, request, classified, *, actor_class: str, commands_help: str) -> dict:
    if not isinstance(classified, dict):
        return {"kind": "ignore"}
    command = classified.get("command")
    args = classified.get("args") or []
    if not isinstance(command, str):
        return {"kind": "ignore"}
    if actor_class in {"unknown_actor", "bot_account", "github_app_or_other_automation"}:
        return {"kind": "ignore"}

    issue_number = request.issue_number
    comment_author = request.comment_author

    if command == "accept-no-fls-changes":
        return {"kind": "deferred_privileged_handoff"}
    if command == "_multiple_commands":
        return {
            "kind": "inline_response",
            "response": f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. For a list of commands, use `{bot.BOT_MENTION} /commands`.",
            "success": False,
            "state_changed": False,
            "react": False,
        }
    if command == "pass":
        return {
            "kind": "handler_call",
            "handler": "handle_pass_command",
            "handler_args": [issue_number, comment_author, " ".join(args) if args else None],
            "needs_assignment_request": True,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "away":
        if args:
            return {
                "kind": "handler_call",
                "handler": "handle_pass_until_command",
                "handler_args": [issue_number, comment_author, args[0], " ".join(args[1:]) if len(args) > 1 else None],
                "needs_assignment_request": True,
                "result_shape": "pair",
                "state_changed_from": "success",
            }
        return {
            "kind": "inline_response",
            "response": f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`",
            "success": False,
            "state_changed": False,
            "react": True,
        }
    if command == "label":
        return {
            "kind": "handler_call",
            "handler": "handle_label_command",
            "handler_args": [issue_number, " ".join(args)],
            "needs_assignment_request": True,
            "result_shape": "triple",
        }
    if command == "sync-members":
        return {
            "kind": "handler_call",
            "handler": "handle_sync_members_command",
            "handler_args": [],
            "needs_assignment_request": False,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "queue":
        return {
            "kind": "handler_call",
            "handler": "handle_queue_command",
            "handler_args": [],
            "needs_assignment_request": False,
            "result_shape": "pair",
            "state_changed_from": "never",
        }
    if command == "commands":
        return {
            "kind": "handler_call",
            "handler": "handle_commands_command",
            "handler_args": [],
            "needs_assignment_request": False,
            "result_shape": "pair",
            "state_changed_from": "never",
        }
    if command == "claim":
        return {
            "kind": "handler_call",
            "handler": "handle_claim_command",
            "handler_args": [issue_number, comment_author],
            "needs_assignment_request": True,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "release":
        return {
            "kind": "handler_call",
            "handler": "handle_release_command",
            "handler_args": [issue_number, comment_author, list(args)],
            "needs_assignment_request": True,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "rectify":
        return {
            "kind": "handler_call",
            "handler": "handle_rectify_command",
            "handler_args": [issue_number, comment_author],
            "needs_assignment_request": False,
            "result_shape": "triple",
        }
    if command == "r?-user":
        return {
            "kind": "handler_call",
            "handler": "handle_assign_command",
            "handler_args": [issue_number, args[0] if args else ""],
            "needs_assignment_request": True,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "assign-from-queue":
        return {
            "kind": "handler_call",
            "handler": "handle_assign_from_queue_command",
            "handler_args": [issue_number],
            "needs_assignment_request": True,
            "result_shape": "pair",
            "state_changed_from": "success",
        }
    if command == "r?":
        return {
            "kind": "inline_response",
            "response": f"❌ Missing target. Usage:\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Assign next reviewer from queue",
            "success": False,
            "state_changed": False,
            "react": True,
        }
    if command == "_malformed_known":
        attempted = args[0] if args else "command"
        return {
            "kind": "inline_response",
            "response": f"⚠️ Did you mean `{bot.BOT_MENTION} /{attempted}`?\n\nCommands require a `/` prefix.",
            "success": False,
            "state_changed": False,
            "react": True,
        }
    if command == "_malformed_unknown":
        attempted = args[0] if args else ""
        return {
            "kind": "inline_response",
            "response": f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\nTry `{bot.BOT_MENTION} /commands` to see available commands.",
            "success": False,
            "state_changed": False,
            "react": True,
        }
    return {
        "kind": "inline_response",
        "response": f"❌ Unknown command: `/{command}`\n\nAvailable commands:\n{commands_help}",
        "success": False,
        "state_changed": False,
        "react": True,
    }
