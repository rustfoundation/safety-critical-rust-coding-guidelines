"""Reviewer-bot command parsing and handlers."""

import re
from datetime import datetime, timezone

from .automation import bot_parse_issue_labels
from .automation import (
    find_open_pr_for_branch_status as automation_find_open_pr_for_branch_status,
)
from .config import AssignmentAttempt
from .context import AssignmentRequest, PrivilegedCommandRequest
from .event_inputs import build_assignment_request as decode_assignment_request
from .event_inputs import (
    build_privileged_command_request as decode_privileged_command_request,
)
from .guidance import get_issue_guidance, get_pr_guidance


def build_assignment_request(*, issue_number: int) -> AssignmentRequest:
    return decode_assignment_request(issue_number=issue_number)


def build_privileged_command_request(*, issue_number: int, actor: str = "", command_name: str = "") -> PrivilegedCommandRequest:
    return decode_privileged_command_request(
        issue_number=issue_number,
        actor=actor,
        command_name=command_name,
    )


def strip_code_blocks(comment_body: str) -> str:
    sanitized = comment_body

    def strip_fenced_blocks(text: str, fence: str) -> str:
        pattern = re.compile(re.escape(fence) + r".*?" + re.escape(fence), re.DOTALL)
        stripped = pattern.sub("", text)
        last_fence = stripped.rfind(fence)
        if last_fence != -1:
            stripped = stripped[:last_fence]
        return stripped

    sanitized = strip_fenced_blocks(sanitized, "```")
    sanitized = strip_fenced_blocks(sanitized, "~~~")
    sanitized = re.sub(r"^(?: {4}|\t).*$", "", sanitized, flags=re.MULTILINE)
    sanitized = re.sub(r"`[^`]*`", "", sanitized)
    return sanitized


def parse_command(bot, comment_body: str) -> tuple[str, list[str]] | None:
    mention_pattern = rf"{re.escape(bot.BOT_MENTION)}\s+/\S+"
    pattern = rf"{re.escape(bot.BOT_MENTION)}\s+/(\S+)(.*)$"
    matches = re.findall(mention_pattern, comment_body, re.IGNORECASE | re.MULTILINE)
    if len(matches) > 1:
        return "_multiple_commands", []
    match = re.search(pattern, comment_body, re.IGNORECASE | re.MULTILINE)
    if not match:
        malformed_pattern = rf"{re.escape(bot.BOT_MENTION)}\s+(\S+)"
        malformed_match = re.search(malformed_pattern, comment_body, re.IGNORECASE | re.MULTILINE)
        if malformed_match:
            attempted = malformed_match.group(1).lower()
            conversational = {"i", "we", "you", "the", "a", "an", "is", "are", "can", "could", "would", "should", "please", "thanks", "thank", "hi", "hello", "hey"}
            if attempted in conversational:
                return None
            if attempted in bot.COMMANDS or attempted in {"r?-user", "assign-from-queue"}:
                return "_malformed_known", [attempted]
            return "_malformed_unknown", [attempted]
        return None
    command = match.group(1).lower()
    args_str = match.group(2).strip()
    if command == "r?":
        target = args_str.split()[0] if args_str else ""
        if target.lower() == "producers":
            return "assign-from-queue", []
        if target:
            username = target.lstrip("@")
            return "r?-user", [f"@{username}"]
        return "r?", []
    args = []
    if args_str:
        current_arg = ""
        in_quotes = False
        quote_char = None
        for char in args_str:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
            elif char.isspace() and not in_quotes:
                if current_arg:
                    args.append(current_arg)
                    current_arg = ""
            else:
                current_arg += char
        if current_arg:
            args.append(current_arg)
    return command, args


def _apply_assignment_side_effects(
    bot,
    state: dict,
    request: AssignmentRequest,
    reviewer: str,
    assignment_method: str,
) -> tuple[AssignmentAttempt, str | None]:
    issue_number = request.issue_number
    assignment_attempt = bot.request_reviewer_assignment(issue_number, reviewer)
    bot.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)
    bot.record_assignment(state, reviewer, issue_number, "pr" if request.is_pull_request else "issue")
    failure_comment = bot.get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        bot.post_comment(issue_number, failure_comment)
    if assignment_attempt.success:
        if request.is_pull_request:
            bot.post_comment(issue_number, get_pr_guidance(reviewer, request.issue_author))
        else:
            labels = set(request.issue_labels)
            guidance = (
                bot.get_fls_audit_guidance(reviewer, request.issue_author)
                if bot.FLS_AUDIT_LABEL in labels
                else get_issue_guidance(reviewer, request.issue_author)
            )
            bot.post_comment(issue_number, guidance)
    return assignment_attempt, failure_comment


def _current_assignees_or_error(bot, issue_number: int) -> tuple[list[str] | None, str | None]:
    current_assignees = bot.get_issue_assignees(issue_number)
    if current_assignees is None:
        return None, "❌ Unable to determine current assignees/reviewers from GitHub; refusing to continue."
    return current_assignees, None


def handle_pass_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    reason: str | None,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    issue_data = bot.ensure_review_entry(state, issue_number, create=True)
    if issue_data is None:
        return "❌ Unable to load review state.", False
    passed_reviewer = issue_data.get("current_reviewer")
    if not passed_reviewer:
        current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
        if assignee_error:
            return assignee_error, False
        passed_reviewer = current_assignees[0] if current_assignees else None
    if not passed_reviewer:
        return "❌ No reviewer is currently assigned to pass.", False
    if passed_reviewer.lower() != comment_author.lower():
        return "❌ Only the currently assigned reviewer can use `/pass`.", False
    is_first_pass = len(issue_data["skipped"]) == 0
    if passed_reviewer not in issue_data["skipped"]:
        issue_data["skipped"].append(passed_reviewer)
    skip_set = set(issue_data["skipped"])
    if assignment_request.issue_author:
        skip_set.add(assignment_request.issue_author)
    next_reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
    if not next_reviewer:
        return ("❌ No other reviewers available. Everyone in the queue has either passed on this issue or is the author."), False
    bot.reposition_member_as_next(state, passed_reviewer)
    bot.unassign_reviewer(issue_number, passed_reviewer)
    assignment_attempt, failure_comment = _apply_assignment_side_effects(
        bot,
        state,
        assignment_request,
        next_reviewer,
        "round-robin",
    )
    assignment_line = f"@{next_reviewer} is now assigned as the reviewer."
    if not assignment_attempt.success:
        if failure_comment:
            assignment_line = failure_comment
        else:
            status_text = assignment_attempt.status_code or "unknown"
            assignment_line = f"@{next_reviewer} is designated as reviewer in bot state, but GitHub assignment could not be confirmed (status {status_text})."
    reason_text = f" Reason: {reason}" if reason else ""
    if is_first_pass:
        return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n{assignment_line}\n\n_@{passed_reviewer} is next in queue for future issues._"), True
    original_passer = issue_data["skipped"][0]
    return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n{assignment_line}\n\n_@{original_passer} remains next in queue for future issues._"), True


def handle_pass_until_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    return_date: str,
    reason: str | None,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    try:
        parsed_date = datetime.strptime(return_date, "%Y-%m-%d").date()
    except ValueError:
        return (f"❌ Invalid date format: `{return_date}`. Please use YYYY-MM-DD format (e.g., 2025-02-01)."), False
    if parsed_date <= datetime.now(timezone.utc).date():
        return "❌ Return date must be in the future.", False
    user_in_queue = None
    user_index = None
    for index, member in enumerate(state["queue"]):
        if member["github"].lower() == comment_author.lower():
            user_in_queue = member
            user_index = index
            break
    if not user_in_queue:
        for entry in state.get("pass_until", []):
            if entry["github"].lower() == comment_author.lower():
                entry["return_date"] = return_date
                if reason:
                    entry["reason"] = reason
                return (f"✅ Updated your return date to {return_date}.\n\nYou're already marked as away."), True
        return (f"❌ @{comment_author} is not in the reviewer queue. Only Producers can use this command."), False
    state["queue"].remove(user_in_queue)
    pass_entry = {"github": user_in_queue["github"], "name": user_in_queue.get("name", user_in_queue["github"]), "return_date": return_date, "original_queue_position": user_index}
    if reason:
        pass_entry["reason"] = reason
    state["pass_until"].append(pass_entry)
    if state["queue"]:
        if user_index is not None and user_index < state["current_index"]:
            state["current_index"] = max(0, state["current_index"] - 1)
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            tracked_reviewer = issue_data.get("current_reviewer")
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    is_current_reviewer = ((tracked_reviewer and tracked_reviewer.lower() == comment_author.lower()) or comment_author.lower() in [a.lower() for a in current_assignees])
    reassigned_msg = ""
    if is_current_reviewer:
        bot.unassign_reviewer(issue_number, comment_author)
        skip_set = {assignment_request.issue_author} if assignment_request.issue_author else set()
        next_reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
        if next_reviewer:
            assignment_attempt, failure_comment = _apply_assignment_side_effects(
                bot,
                state,
                assignment_request,
                next_reviewer,
                "round-robin",
            )
            if assignment_attempt.success:
                reassigned_msg = f"\n\n@{next_reviewer} has been assigned as the new reviewer for this issue."
            else:
                if failure_comment:
                    reassigned_msg = f"\n\n{failure_comment}"
                else:
                    status_text = assignment_attempt.status_code or "unknown"
                    reassigned_msg = f"\n\n@{next_reviewer} is designated as the new reviewer in bot state, but GitHub assignment is not confirmed (status {status_text})."
        else:
            if "active_reviews" in state and issue_key in state["active_reviews"] and isinstance(state["active_reviews"][issue_key], dict):
                state["active_reviews"][issue_key]["current_reviewer"] = None
            reassigned_msg = "\n\n⚠️ No other reviewers available to assign."
    reason_text = f" ({reason})" if reason else ""
    return (f"✅ @{comment_author} is now away until {return_date}{reason_text}.\n\nYou'll be automatically added back to the queue on that date.{reassigned_msg}"), True


def handle_label_command(
    bot,
    state: dict,
    issue_number: int,
    label_string: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    pattern = r'(?:(?<=^)|(?<=\s))([+-])(.+?)(?=\s[+-]|\s*$)'
    matches = re.findall(pattern, label_string)
    if not matches:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False, False
    existing_labels = bot.get_repo_labels()
    results = []
    all_success = True
    state_changed = False
    for action, label in matches:
        label = label.strip()
        if not label:
            continue
        if action == "+":
            if label not in existing_labels:
                results.append(f"⚠️ Label `{label}` does not exist in this repository")
                all_success = False
            elif bot.add_label(issue_number, label):
                results.append(f"✅ Added label `{label}`")
                if label == "sign-off: create pr" and not assignment_request.is_pull_request:
                    review_data = bot.ensure_review_entry(state, issue_number)
                    reviewer = review_data.get("current_reviewer") if review_data else None
                    completion_changed = bot.mark_review_complete(
                        state, issue_number, reviewer, "issue_label: sign-off: create pr"
                    )
                    state_changed = completion_changed or state_changed
            else:
                results.append(f"❌ Failed to add label `{label}`")
                all_success = False
        elif action == "-":
            if bot.remove_label(issue_number, label):
                results.append(f"✅ Removed label `{label}`")
            else:
                results.append(f"❌ Failed to remove label `{label}`")
                all_success = False
    if not results:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False, False
    return "\n".join(results), all_success, state_changed


def parse_issue_labels() -> list[str]:
    return bot_parse_issue_labels()


def get_default_branch(bot) -> str:
    repo_info = bot.github_api("GET", "")
    if isinstance(repo_info, dict):
        return repo_info.get("default_branch", "main")
    return "main"


def find_open_pr_for_branch(bot, branch: str) -> dict | None:
    status, pr = automation_find_open_pr_for_branch_status(bot, branch)
    if status != "found":
        return None
    return pr


def resolve_workflow_run_pr_number(
    bot,
    request: PrivilegedCommandRequest | None = None,
) -> int:
    privileged_request = request or build_privileged_command_request(issue_number=0)
    if privileged_request.workflow_run_reconcile_pr_number is None:
        raise RuntimeError("Missing WORKFLOW_RUN_RECONCILE_PR_NUMBER in workflow_run reconcile context")
    pr_number = privileged_request.workflow_run_reconcile_pr_number
    if pr_number <= 0:
        raise RuntimeError("WORKFLOW_RUN_RECONCILE_PR_NUMBER must be a positive integer")
    reconcile_head_sha = privileged_request.workflow_run_reconcile_head_sha
    if not reconcile_head_sha:
        raise RuntimeError("Missing WORKFLOW_RUN_RECONCILE_HEAD_SHA in workflow_run reconcile context")
    workflow_run_head_sha = privileged_request.workflow_run_head_sha
    if not workflow_run_head_sha:
        raise RuntimeError("Missing WORKFLOW_RUN_HEAD_SHA for workflow_run reconcile")
    if reconcile_head_sha != workflow_run_head_sha:
        raise RuntimeError("Workflow_run reconcile context SHA mismatch between artifact and workflow payload")
    response = bot.github_api_request("GET", f"pulls/{pr_number}", retry_policy="idempotent_read")
    if not response.ok or not isinstance(response.payload, dict):
        raise RuntimeError(f"Failed to fetch pull request #{pr_number} during workflow_run reconcile")
    pull_request = response.payload
    head = pull_request.get("head")
    pull_request_head_sha = ""
    if isinstance(head, dict):
        head_sha = head.get("sha")
        if isinstance(head_sha, str):
            pull_request_head_sha = head_sha.strip()
    if not pull_request_head_sha:
        raise RuntimeError(f"Pull request #{pr_number} is missing a valid head SHA")
    if pull_request_head_sha != reconcile_head_sha:
        raise RuntimeError(f"Pull request #{pr_number} head SHA does not match workflow_run reconcile context")
    print(f"Resolved workflow_run PR from reconcile context: #{pr_number}")
    return pr_number


def handle_sync_members_command(bot, state: dict) -> tuple[str, bool]:
    state, changes = bot.sync_members_with_queue(state)
    if changes:
        changes_text = "\n".join(f"- {change}" for change in changes)
        return f"✅ Queue synced with members.md:\n\n{changes_text}", True
    return "✅ Queue is already in sync with members.md.", True


def handle_queue_command(
    bot,
    state: dict,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=0)
    queue_size = len(state["queue"])
    repo_owner = assignment_request.repo_owner
    repo_name = assignment_request.repo_name
    state_issue_link = ""
    if repo_owner and repo_name and bot.STATE_ISSUE_NUMBER:
        state_issue_link = f"\n\n[View full state details](https://github.com/{repo_owner}/{repo_name}/issues/{bot.STATE_ISSUE_NUMBER})"
    if queue_size == 0:
        return f"📊 **Queue Status**: No reviewers in queue.{state_issue_link}", True
    current_index = state["current_index"]
    next_up = state["queue"][current_index]["github"]
    queue_list = []
    for index, member in enumerate(state["queue"]):
        marker = "→" if index == current_index else " "
        queue_list.append(f"{marker} {index + 1}. @{member['github']}")
    queue_text = "\n".join(queue_list)
    away_text = ""
    if state.get("pass_until"):
        away_list = []
        for entry in state["pass_until"]:
            reason = f" ({entry['reason']})" if entry.get("reason") else ""
            away_list.append(f"- @{entry['github']} until {entry['return_date']}{reason}")
        away_text = "\n\n**Currently Away:**\n" + "\n".join(away_list)
    return (f"📊 **Queue Status**\n\n**Next up:** @{next_up}\n\n**Queue ({queue_size} reviewers):**\n```\n{queue_text}\n```{away_text}{state_issue_link}"), True


def handle_commands_command(bot) -> tuple[str, bool]:
    return (f"ℹ️ **Available Commands**\n\n**Pass or step away:**\n- `{bot.BOT_MENTION} /pass [reason]` - Pass this review to next in queue (current reviewer only)\n- `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from queue until a date\n- `{bot.BOT_MENTION} /release [@username] [reason]` - Release assignment (yours or someone else's with triage+ permission)\n\n**Assign reviewers:**\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Request the next reviewer from the queue\n- `{bot.BOT_MENTION} /claim` - Claim this review for yourself\n\n**Other:**\n- `{bot.BOT_MENTION} /label +label-name` - Add a label\n- `{bot.BOT_MENTION} /label -label-name` - Remove a label\n- `{bot.BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub\n- `{bot.BOT_MENTION} /accept-no-fls-changes` - Update spec.lock and open a PR when no guidelines are impacted\n- `{bot.BOT_MENTION} /queue` - Show current queue status\n- `{bot.BOT_MENTION} /sync-members` - Sync queue with members.md"), True


def handle_claim_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    is_producer = any(member["github"].lower() == comment_author.lower() for member in state["queue"])
    is_away = any(member["github"].lower() == comment_author.lower() for member in state.get("pass_until", []))
    if not is_producer and not is_away:
        return (f"❌ @{comment_author} is not in the reviewer queue. Only Producers can claim reviews."), False
    if is_away:
        return (f"❌ @{comment_author} is currently marked as away. Please use `{bot.BOT_MENTION} /away YYYY-MM-DD` to update your return date first, or wait until your scheduled return."), False
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    for assignee in current_assignees:
        bot.unassign_reviewer(issue_number, assignee)
    assignment_attempt, failure_comment = _apply_assignment_side_effects(
        bot,
        state,
        assignment_request,
        comment_author,
        "claim",
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    response = f"✅ @{comment_author} has claimed this review{prev_text}."
    if not assignment_attempt.success:
        if failure_comment:
            response = f"{response}\n\n{failure_comment}"
    return response, True


def handle_release_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    args: list | None = None,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    args = args or []
    request = request or build_assignment_request(issue_number=issue_number)
    target_username = None
    reason = None
    releasing_other = False
    if args and args[0].startswith("@"):
        target_username = args[0].lstrip("@")
        reason = " ".join(args[1:]) if len(args) > 1 else None
        releasing_other = target_username.lower() != comment_author.lower()
        permission_status = bot.get_user_permission_status(comment_author, "triage")
        if permission_status == "unavailable":
            return "❌ Unable to verify triage permissions right now; refusing to continue.", False
        if releasing_other and permission_status != "granted":
            return (f"❌ @{comment_author} does not have permission to release other reviewers. Triage access or higher is required."), False
    else:
        target_username = comment_author
        reason = " ".join(args) if args else None
    issue_key = str(issue_number)
    tracked_reviewer = None
    assignment_method = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            tracked_reviewer = issue_data.get("current_reviewer")
            assignment_method = issue_data.get("assignment_method")
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    is_tracked = tracked_reviewer and tracked_reviewer.lower() == target_username.lower()
    is_assigned = target_username.lower() in [assignee.lower() for assignee in current_assignees]
    if not is_tracked and not is_assigned:
        if releasing_other:
            if tracked_reviewer:
                return (f"❌ @{target_username} is not the current reviewer. Current reviewer: @{tracked_reviewer}"), False
            if current_assignees:
                return (f"❌ @{target_username} is not assigned to this issue/PR. Current assignee(s): @{', @'.join(current_assignees)}"), False
            return f"❌ @{target_username} is not assigned to this issue/PR.", False
        if tracked_reviewer:
            return (f"❌ @{comment_author} is not the current reviewer. Current reviewer: @{tracked_reviewer}"), False
        if current_assignees:
            return (f"❌ @{comment_author} is not assigned to this issue/PR. Current assignee(s): @{', @'.join(current_assignees)}"), False
        return "❌ No reviewer is currently assigned to release.", False
    bot.unassign_reviewer(issue_number, target_username)
    if "active_reviews" in state and issue_key in state["active_reviews"] and isinstance(state["active_reviews"][issue_key], dict):
        state["active_reviews"][issue_key]["current_reviewer"] = None
    if assignment_method == "round-robin":
        bot.reposition_member_as_next(state, target_username)
    reason_text = f" Reason: {reason}" if reason else ""
    if releasing_other:
        return (f"✅ @{comment_author} has released @{target_username} from this review.{reason_text}\n\n_This issue/PR is now unassigned. Use `{bot.BOT_MENTION} /r? producers` to assign the next reviewer from the queue, or `{bot.BOT_MENTION} /claim` to claim it._"), True
    return (f"✅ @{target_username} has released this review.{reason_text}\n\n_This issue/PR is now unassigned. Use `{bot.BOT_MENTION} /r? producers` to assign the next reviewer from the queue, or `{bot.BOT_MENTION} /claim` to claim it._"), True


def handle_assign_command(
    bot,
    state: dict,
    issue_number: int,
    username: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    username = username.lstrip("@")
    if not username:
        return (f"❌ Missing username. Usage: `{bot.BOT_MENTION} /r? @username`"), False
    is_producer = any(member["github"].lower() == username.lower() for member in state["queue"])
    is_away = any(member["github"].lower() == username.lower() for member in state.get("pass_until", []))
    if not is_producer and not is_away:
        return (f"⚠️ @{username} is not in the reviewer queue (not a Producer). Assigning anyway, but they may not have review permissions."), False
    if is_away:
        for entry in state.get("pass_until", []):
            if entry["github"].lower() == username.lower():
                return_date = entry.get("return_date", "unknown")
                return (f"⚠️ @{username} is currently marked as away until {return_date}. Consider assigning someone else or waiting."), False
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    for assignee in current_assignees:
        bot.unassign_reviewer(issue_number, assignee)
    assignment_attempt, failure_comment = _apply_assignment_side_effects(
        bot,
        state,
        assignment_request,
        username,
        "manual",
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    if assignment_attempt.success:
        return f"✅ @{username} has been assigned as reviewer{prev_text}.", True
    response = f"✅ @{username} remains designated as reviewer in bot state{prev_text}. GitHub reviewer assignment could not be completed."
    if failure_comment:
        response = f"{response}\n\n{failure_comment}"
    return response, True


def handle_assign_from_queue_command(
    bot,
    state: dict,
    issue_number: int,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(issue_number=issue_number)
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    for assignee in current_assignees:
        bot.unassign_reviewer(issue_number, assignee)
    skip_set = {assignment_request.issue_author} if assignment_request.issue_author else set()
    next_reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
    if not next_reviewer:
        return (f"❌ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue."), False
    assignment_attempt, _failure_comment = _apply_assignment_side_effects(
        bot,
        state,
        assignment_request,
        next_reviewer,
        "round-robin",
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    if assignment_attempt.success:
        return f"✅ @{next_reviewer} (next in queue) has been assigned as reviewer{prev_text}.", True
    return (f"✅ @{next_reviewer} remains designated as reviewer in bot state{prev_text}. GitHub reviewer assignment could not be completed."), True
