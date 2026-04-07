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

from dataclasses import dataclass


@dataclass(frozen=True)
class OrdinaryCommentUseCaseResult:
    kind: str
    handler_name: str | None
    handler_args: list[object] | None
    needs_assignment_request: bool
    result_shape: str | None
    state_changed_from: str
    response: str | None
    success: bool | None
    react: bool


def _handler_call(
    handler_name: str,
    handler_args: list[object],
    *,
    needs_assignment_request: bool,
    result_shape: str,
    state_changed_from: str,
) -> OrdinaryCommentUseCaseResult:
    return OrdinaryCommentUseCaseResult(
        kind="handler_call",
        handler_name=handler_name,
        handler_args=handler_args,
        needs_assignment_request=needs_assignment_request,
        result_shape=result_shape,
        state_changed_from=state_changed_from,
        response=None,
        success=None,
        react=True,
    )


def _inline_response(response: str, *, success: bool, react: bool) -> OrdinaryCommentUseCaseResult:
    return OrdinaryCommentUseCaseResult(
        kind="inline_response",
        handler_name=None,
        handler_args=None,
        needs_assignment_request=False,
        result_shape=None,
        state_changed_from="never",
        response=response,
        success=success,
        react=react,
    )


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
        return _inline_response(
            f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. For a list of commands, use `{bot.BOT_MENTION} /commands`.",
            success=False,
            react=False,
        )
    if command == "pass":
        return _handler_call(
            "handle_pass_command",
            [issue_number, comment_author, " ".join(args) if args else None],
            needs_assignment_request=True,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "away":
        if args:
            return _handler_call(
                "handle_pass_until_command",
                [issue_number, comment_author, args[0], " ".join(args[1:]) if len(args) > 1 else None],
                needs_assignment_request=True,
                result_shape="pair",
                state_changed_from="success",
            )
        return _inline_response(
            f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`",
            success=False,
            react=True,
        )
    if command == "label":
        return _handler_call(
            "handle_label_command",
            [issue_number, " ".join(args)],
            needs_assignment_request=True,
            result_shape="triple",
            state_changed_from="handler_return",
        )
    if command == "sync-members":
        return _handler_call(
            "handle_sync_members_command",
            [],
            needs_assignment_request=False,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "queue":
        return _handler_call(
            "handle_queue_command",
            [],
            needs_assignment_request=False,
            result_shape="pair",
            state_changed_from="never",
        )
    if command == "commands":
        return _handler_call(
            "handle_commands_command",
            [],
            needs_assignment_request=False,
            result_shape="pair",
            state_changed_from="never",
        )
    if command == "claim":
        return _handler_call(
            "handle_claim_command",
            [issue_number, comment_author],
            needs_assignment_request=True,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "release":
        return _handler_call(
            "handle_release_command",
            [issue_number, comment_author, list(args)],
            needs_assignment_request=True,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "rectify":
        return _handler_call(
            "handle_rectify_command",
            [issue_number, comment_author],
            needs_assignment_request=False,
            result_shape="triple",
            state_changed_from="handler_return",
        )
    if command == "r?-user":
        return _handler_call(
            "handle_assign_command",
            [issue_number, args[0] if args else ""],
            needs_assignment_request=True,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "assign-from-queue":
        return _handler_call(
            "handle_assign_from_queue_command",
            [issue_number],
            needs_assignment_request=True,
            result_shape="pair",
            state_changed_from="success",
        )
    if command == "r?":
        return _inline_response(
            f"❌ Missing target. Usage:\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Assign next reviewer from queue",
            success=False,
            react=True,
        )
    if command == "_malformed_known":
        attempted = args[0] if args else "command"
        return _inline_response(
            f"⚠️ Did you mean `{bot.BOT_MENTION} /{attempted}`?\n\nCommands require a `/` prefix.",
            success=False,
            react=True,
        )
    if command == "_malformed_unknown":
        attempted = args[0] if args else ""
        return _inline_response(
            f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\nTry `{bot.BOT_MENTION} /commands` to see available commands.",
            success=False,
            react=True,
        )
    return _inline_response(
        f"❌ Unknown command: `/{command}`\n\nAvailable commands:\n{commands_help}",
        success=False,
        react=True,
    )
