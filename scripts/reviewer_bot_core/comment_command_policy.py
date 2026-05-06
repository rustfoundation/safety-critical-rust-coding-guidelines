"""Command decision owner for already-routed comment events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import privileged_command_policy


class OrdinaryCommandId(StrEnum):
    PASS = "pass"
    AWAY = "away"
    FEEDBACK = "feedback"
    DONE = "done"
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


@dataclass(frozen=True)
class AssignmentCommandAuthorization:
    command_name: str
    actor: str
    issue_number: int
    target: str | None
    current_reviewer: str | None
    is_assigned: bool
    actor_permission: str
    authorized: bool
    reason: str

    def to_output(self) -> dict[str, object]:
        return {
            "command_name": self.command_name,
            "actor": self.actor,
            "issue_number": self.issue_number,
            "target": self.target,
            "current_reviewer": self.current_reviewer,
            "is_assigned": self.is_assigned,
            "actor_permission": self.actor_permission,
            "authorized": self.authorized,
            "reason": self.reason,
        }


CommentCommandDecision = (
    IgnoreDecision
    | InlineResponseDecision
    | DeferPrivilegedHandoffDecision
    | ExecuteOrdinaryCommandDecision
)


def authorize_assignment_command(
    command_name: str,
    *,
    actor: str,
    issue_number: int,
    target: str | None,
    current_reviewer: str | None,
    actor_permission: str,
) -> AssignmentCommandAuthorization:
    actor_login = actor.strip() if isinstance(actor, str) else ""
    if not actor_login:
        return AssignmentCommandAuthorization(
            command_name=command_name,
            actor="",
            issue_number=issue_number,
            target=target,
            current_reviewer=current_reviewer,
            is_assigned=False,
            actor_permission="unknown",
            authorized=False,
            reason="missing_actor",
        )
    if not isinstance(issue_number, int) or issue_number <= 0:
        return AssignmentCommandAuthorization(
            command_name=command_name,
            actor=actor_login,
            issue_number=issue_number,
            target=target,
            current_reviewer=current_reviewer,
            is_assigned=False,
            actor_permission="unknown",
            authorized=False,
            reason="malformed_issue_number",
        )
    permission = actor_permission.strip().lower() if isinstance(actor_permission, str) else ""
    if permission in {"", "unknown", "unavailable"}:
        return AssignmentCommandAuthorization(
            command_name=command_name,
            actor=actor_login,
            issue_number=issue_number,
            target=target,
            current_reviewer=current_reviewer,
            is_assigned=False,
            actor_permission=permission or "unknown",
            authorized=False,
            reason="permission_unavailable",
        )
    is_assigned = (
        isinstance(current_reviewer, str)
        and current_reviewer.strip()
        and actor_login.lower() == current_reviewer.lower()
    )
    triage_or_better = permission in {"admin", "maintain", "write", "triage", "granted"}
    if command_name == OrdinaryCommandId.ASSIGN_SPECIFIC.value:
        authorized = triage_or_better
        reason = "triage_override" if triage_or_better else "actor_not_authorized"
    elif command_name in {OrdinaryCommandId.ASSIGN_FROM_QUEUE.value, "r?"}:
        unassigned = not (isinstance(current_reviewer, str) and current_reviewer.strip())
        authorized = triage_or_better or is_assigned
        if not authorized and unassigned and (target or "").lower() == "producers":
            authorized = True
            reason = "unassigned_queue_request"
        else:
            reason = "triage_override" if triage_or_better else "assigned_reviewer_pass_semantics" if is_assigned else "actor_not_authorized"
    else:
        authorized = False
        reason = "not_assignment_command"
    return AssignmentCommandAuthorization(
        command_name=command_name,
        actor=actor_login,
        issue_number=issue_number,
        target=target,
        current_reviewer=current_reviewer,
        is_assigned=bool(is_assigned),
        actor_permission=permission or "unknown",
        authorized=authorized,
        reason=reason,
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
    if command == OrdinaryCommandId.FEEDBACK.value:
        if args:
            return InlineResponseDecision(
                response=f"❌ `/feedback` does not accept arguments. Usage: `{bot.BOT_MENTION} /feedback`",
                success=False,
                react=True,
            )
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.FEEDBACK,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=(),
            needs_assignment_request=False,
        )
    if command == "_malformed_feedback_args":
        return InlineResponseDecision(
            response=f"❌ `/feedback` does not accept arguments. Usage: `{bot.BOT_MENTION} /feedback`",
            success=False,
            react=True,
        )
    if command == OrdinaryCommandId.DONE.value:
        return ExecuteOrdinaryCommandDecision(
            command_id=OrdinaryCommandId.DONE,
            issue_number=issue_number,
            actor=comment_author,
            raw_args=args,
            needs_assignment_request=True,
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
