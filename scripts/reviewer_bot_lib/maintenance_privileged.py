"""Pending privileged maintenance seam for reviewer-bot."""

from __future__ import annotations

from scripts.reviewer_bot_core import privileged_command_policy

from . import automation


def _now_iso(bot) -> str:
    return bot.clock.now().isoformat()


def execute_pending_privileged_command(bot, state: dict, source_event_key: str) -> bool:
    pending = privileged_command_policy.find_pending_accept_no_fls_changes(state, source_event_key)
    if pending is None:
        raise RuntimeError(f"Pending privileged command not found for {source_event_key}")
    issue_number, review_data, record = pending
    if record.status != "pending":
        return False
    actor = record.actor.strip()
    if record.command_name != privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value:
        privileged_command_policy.mark_pending_accept_no_fls_changes_failed_closed(
            review_data,
            source_event_key,
            completed_at=_now_iso(bot),
            result="unsupported_command",
        )
        return True
    issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
    permission_status = bot.github.get_user_permission_status(actor, "triage")
    revalidation = privileged_command_policy.revalidate_pending_accept_no_fls_changes(
        record,
        issue_snapshot,
        permission_status,
        target_repo_root=str(automation.get_target_repo_root(bot)),
    )
    if isinstance(revalidation, privileged_command_policy.BlockedPrivilegedExecution):
        privileged_command_policy.mark_pending_accept_no_fls_changes_failed_closed(
            review_data,
            source_event_key,
            completed_at=_now_iso(bot),
            result=revalidation.result_code,
            result_message=revalidation.result_message,
        )
        return True
    execution = automation.handle_accept_no_fls_changes_command(
        bot,
        issue_number,
        actor,
        execution_plan=revalidation,
    )
    if execution.status == "executed":
        privileged_command_policy.mark_pending_accept_no_fls_changes_executed(
            review_data,
            source_event_key,
            completed_at=_now_iso(bot),
            result=execution.result_code,
            result_message=execution.result_message or "",
            opened_pr_url=execution.opened_pr_url,
        )
        return True
    privileged_command_policy.mark_pending_accept_no_fls_changes_failed_closed(
        review_data,
        source_event_key,
        completed_at=_now_iso(bot),
        result=execution.result_code,
        result_message=execution.result_message,
    )
    return True
