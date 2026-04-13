"""Command decision owner for already-routed comment events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import privileged_command_policy


class OrdinaryCommandId(StrEnum):
    PASS = "pass"
    AWAY = "away"
    LABEL = "label"
    SYNC_MEMBERS = "sync-members"
    QUEUE = "queue"
    COMMANDS = "commands"
    CLAIM = "claim"
    RELEASE = "release"
    RECTIFY = "rectify"
    ASSIGN_SPECIFIC = "r?-user"
    ASSIGN_FROM_QUEUE = "assign-from-queue"


@dataclass(frozen=True)
class IgnoreDecision:
    pass


@dataclass(frozen=True)
class InlineResponseDecision:
    response: str
    success: bool
    react: bool


@dataclass(frozen=True)
class DeferPrivilegedHandoffDecision:
    command_id: privileged_command_policy.PrivilegedCommandId


@dataclass(frozen=True)
class ExecuteOrdinaryCommandDecision:
    command_id: OrdinaryCommandId
    issue_number: int
    actor: str
    raw_args: tuple[str, ...]
    needs_assignment_request: bool


CommentCommandDecision = (
    IgnoreDecision
    | InlineResponseDecision
    | DeferPrivilegedHandoffDecision
    | ExecuteOrdinaryCommandDecision
)


def decide_comment_command(bot, request, classified, *, actor_class: str, commands_help: str) -> CommentCommandDecision:
    if not isinstance(classified, dict):
        return IgnoreDecision()
    command = classified.get("command")
    args = tuple(classified.get("args") or [])
    if not isinstance(command, str):
        return IgnoreDecision()
    if actor_class in {"unknown_actor", "bot_account", "github_app_or_other_automation"}:
        return IgnoreDecision()

    issue_number = request.issue_number
    comment_author = request.comment_author

    if command == privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value:
        return DeferPrivilegedHandoffDecision(privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES)
    if command == "_multiple_commands":
        return InlineResponseDecision(
            response=(
                f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. "
                f"For a list of commands, use `{bot.BOT_MENTION} /commands`."
            ),
            success=False,
            react=False,
        )
    if command == OrdinaryCommandId.PASS.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.PASS,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == OrdinaryCommandId.AWAY.value:
        if args:
            return ExecuteOrdinaryCommandDecision(
                command_id=OrdinaryCommandId.AWAY,
                issue_number=issue_number,
                actor=comment_author,
                raw_args=args,
                needs_assignment_request=True,
            )
        return InlineResponseDecision(
            response=f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`",
            success=False,
            react=True,
        )
    if command == OrdinaryCommandId.LABEL.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.LABEL,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == OrdinaryCommandId.SYNC_MEMBERS.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.SYNC_MEMBERS,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=False,
        )
    if command == OrdinaryCommandId.QUEUE.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.QUEUE,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=False,
        )
    if command == OrdinaryCommandId.COMMANDS.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.COMMANDS,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=False,
        )
    if command == OrdinaryCommandId.CLAIM.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.CLAIM,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == OrdinaryCommandId.RELEASE.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.RELEASE,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == OrdinaryCommandId.RECTIFY.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.RECTIFY,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=False,
        )
    if command == OrdinaryCommandId.ASSIGN_SPECIFIC.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.ASSIGN_SPECIFIC,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == OrdinaryCommandId.ASSIGN_FROM_QUEUE.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.ASSIGN_FROM_QUEUE,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
        )
    if command == "r?":
        return InlineResponseDecision(
            response=(
                f"❌ Missing target. Usage:\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n"
                f"- `{bot.BOT_MENTION} /r? producers` - Assign next reviewer from queue"
            ),
            success=False,
            react=True,
        )
    if command == "_malformed_known":
        attempted = args[0] if args else "command"
        return InlineResponseDecision(
            response=f"⚠️ Did you mean `{bot.BOT_MENTION} /{attempted}`?\n\nCommands require a `/` prefix.",
            success=False,
            react=True,
        )
    if command == "_malformed_unknown":
        attempted = args[0] if args else ""
        return InlineResponseDecision(
            response=(
                f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\n"
                f"Try `{bot.BOT_MENTION} /commands` to see available commands."
            ),
            success=False,
            react=True,
        )
    return InlineResponseDecision(
        response=f"❌ Unknown command: `/{command}`\n\nAvailable commands:\n{commands_help}",
        success=False,
        react=True,
    )
