"""Reviewer-bot command parsing and handlers."""

import re
from datetime import datetime

from scripts.reviewer_bot_core import comment_command_policy

from . import assignment_flow, review_state
from .config import CODING_GUIDELINE_LABEL
from .context import AssignmentRequest
from .event_inputs import build_assignment_request as decode_assignment_request


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)

_CONVERSATIONAL_WORDS = {
    "i",
    "we",
    "you",
    "the",
    "a",
    "an",
    "is",
    "are",
    "can",
    "could",
    "would",
    "should",
    "please",
    "thanks",
    "thank",
    "hi",
    "hello",
    "hey",
}


def build_assignment_request(bot, *, issue_number: int) -> AssignmentRequest:
    return decode_assignment_request(bot, issue_number=issue_number)


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
            if attempted in _CONVERSATIONAL_WORDS:
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
    if command == "feedback" and args_str:
        return "_malformed_feedback_args", []
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


def _apply_assignment_transition(
    bot,
    state: dict,
    request: AssignmentRequest,
    reviewer: str,
    assignment_method: str,
    current_assignees: list[str] | None = None,
) -> dict[str, object]:
    return assignment_flow.confirm_reviewer_assignment(
        bot,
        state,
        request,
        reviewer=reviewer,
        assignment_method=assignment_method,
        current_assignees=current_assignees,
        emit_guidance=True,
        emit_failure_comment=False,
    )


def _assignment_command_authorization(
    bot,
    state: dict,
    request: AssignmentRequest,
    *,
    command_name: str,
    actor: str | None,
    target: str | None,
) -> comment_command_policy.AssignmentCommandAuthorization:
    issue_data = review_state.ensure_review_entry(state, request.issue_number)
    current_reviewer = issue_data.get("current_reviewer") if isinstance(issue_data, dict) else None
    actor_login = actor.strip() if isinstance(actor, str) and actor.strip() else ""
    if actor_login:
        actor_permission = bot.github.get_user_permission_status(actor_login, "triage")
    else:
        actor_login = "legacy-direct-command"
        actor_permission = "granted"
    authorization = comment_command_policy.authorize_assignment_command(
        command_name,
        actor=actor_login,
        issue_number=request.issue_number,
        target=target,
        current_reviewer=current_reviewer if isinstance(current_reviewer, str) else None,
        actor_permission=actor_permission,
    )
    if isinstance(issue_data, dict):
        authorizations = issue_data.setdefault("sidecars", {}).setdefault("assignment_command_authorizations", {})
        if isinstance(authorizations, dict):
            key = f"{command_name}:{actor_login or '<missing>'}:{target or '<none>'}"
            authorizations[key] = authorization.to_output()
    return authorization


def _assignment_authorization_failure(command_name: str, authorization) -> str:
    if not authorization.actor:
        return f"❌ Unable to identify the actor for `/{command_name}`; refusing to mutate reviewer assignment."
    if authorization.actor_permission == "unavailable":
        return f"❌ Unable to verify @{authorization.actor}'s assignment permissions right now; refusing to continue."
    return f"❌ @{authorization.actor} is not authorized to use `/{command_name}` for this review."


def _current_assignees_or_error(bot, issue_number: int) -> tuple[list[str] | None, str | None]:
    current_assignees = bot.github.get_issue_assignees(issue_number)
    if current_assignees is None:
        return None, "❌ Unable to determine current assignees/reviewers from GitHub; refusing to continue."
    return current_assignees, None


def _assignment_failure_response(target_reviewer: str, result: dict[str, object], *, prefix: str = "") -> str:
    failure_comment = result.get("failure_comment")
    if isinstance(failure_comment, str) and failure_comment:
        return f"{prefix}{failure_comment}"
    final_assignees = result.get("final_assignees")
    if isinstance(final_assignees, list):
        if not final_assignees:
            return f"{prefix}❌ GitHub could not confirm @{target_reviewer} as reviewer. The issue is now unassigned."
        return f"{prefix}❌ GitHub could not confirm @{target_reviewer} as reviewer. Live assignees remain: @{', @'.join(final_assignees)}."
    return f"{prefix}❌ GitHub could not confirm @{target_reviewer} as reviewer."


def _single_current_assignee_or_error(current_assignees: list[str]) -> tuple[str | None, str | None]:
    if not current_assignees:
        return None, "❌ No reviewer is currently assigned to pass."
    if len(current_assignees) != 1:
        return None, "❌ Unable to confirm a single assigned reviewer from GitHub; refusing to continue."
    return current_assignees[0], None


def _reviewer_command_authority_error(command_name: str, resolution: dict[str, object]) -> str:
    return assignment_flow.reviewer_command_authority_failure_message(command_name, resolution)


def handle_pass_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    reason: str | None,
    request: AssignmentRequest | None = None,
    reviewer_authority: dict[str, object] | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    authority = reviewer_authority or assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        assignment_request,
        actor=comment_author,
    )
    authority = assignment_flow.require_reviewer_command_actor(authority, comment_author)
    if not authority.get("authorized"):
        return _reviewer_command_authority_error("pass", authority), False
    issue_data = authority.get("review_data")
    if not isinstance(issue_data, dict):
        return "❌ Unable to load review state.", False
    passed_reviewer = str(authority["tracked_reviewer"])
    current_assignees = list(authority.get("live_control_plane_reviewers") or [])
    skipped = list(issue_data["skipped"])
    is_first_pass = len(skipped) == 0
    if passed_reviewer not in skipped:
        skipped.append(passed_reviewer)
    skip_set = set(skipped)
    if assignment_request.issue_author:
        skip_set.add(assignment_request.issue_author)
    next_reviewer = bot.adapters.queue.get_next_reviewer(state, skip_usernames=skip_set)
    if not next_reviewer:
        return ("❌ No other reviewers available. Everyone in the queue has either passed on this issue or is the author."), False
    result = _apply_assignment_transition(
        bot,
        state,
        assignment_request,
        next_reviewer,
        "round-robin",
        current_assignees=current_assignees,
    )
    if not result.get("confirmed"):
        return _assignment_failure_response(next_reviewer, result), False, bool(
            result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
        )
    issue_data["skipped"] = skipped
    bot.adapters.queue.reposition_member_as_next(state, passed_reviewer)
    assignment_line = f"@{next_reviewer} is now assigned as the reviewer."
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
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    try:
        parsed_date = datetime.strptime(return_date, "%Y-%m-%d").date()
    except ValueError:
        return (f"❌ Invalid date format: `{return_date}`. Please use YYYY-MM-DD format (e.g., 2025-02-01)."), False
    normalized_return_date = parsed_date.isoformat()
    if parsed_date <= bot.clock.now().date():
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
                entry["return_date"] = normalized_return_date
                if reason:
                    entry["reason"] = reason
                return (f"✅ Updated your return date to {normalized_return_date}.\n\nYou're already marked as away."), True
        return (f"❌ @{comment_author} is not in the reviewer queue. Only Producers can use this command."), False
    pass_entry = {"github": user_in_queue["github"], "name": user_in_queue.get("name", user_in_queue["github"]), "return_date": normalized_return_date, "original_queue_position": user_index}
    if reason:
        pass_entry["reason"] = reason
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    live_reviewer, reviewer_error = _single_current_assignee_or_error(current_assignees)
    is_current_reviewer = reviewer_error is None and isinstance(live_reviewer, str) and live_reviewer.lower() == comment_author.lower()
    reassigned_msg = ""
    if is_current_reviewer:
        skip_set = {assignment_request.issue_author} if assignment_request.issue_author else set()
        skip_set.add(comment_author)
        next_reviewer = bot.adapters.queue.get_next_reviewer(state, skip_usernames=skip_set)
        if next_reviewer:
            result = _apply_assignment_transition(
                bot,
                state,
                assignment_request,
                next_reviewer,
                "round-robin",
                current_assignees=current_assignees,
            )
            if result.get("confirmed"):
                reassigned_msg = f"\n\n@{next_reviewer} has been assigned as the new reviewer for this issue."
            else:
                reassigned_msg = f"\n\n{_assignment_failure_response(next_reviewer, result)}"
                return reassigned_msg.strip(), False, bool(
                    result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
                )
        else:
            release_result = assignment_flow.confirm_reviewer_release(
                bot,
                state,
                assignment_request,
                reviewer=comment_author,
            )
            reassigned_msg = (
                "\n\n⚠️ No other reviewers available to assign."
                if release_result.get("confirmed")
                else f"\n\n{_assignment_failure_response(comment_author, release_result)}"
            )
            if not release_result.get("confirmed"):
                return reassigned_msg.strip(), False, bool(
                    release_result.get("diagnostic_changed") or release_result.get("cleared_current_reviewer")
                )
    state["queue"].remove(user_in_queue)
    state["pass_until"].append(pass_entry)
    if state["queue"]:
        if user_index is not None and user_index < state["current_index"]:
            state["current_index"] = max(0, state["current_index"] - 1)
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0
    reason_text = f" ({reason})" if reason else ""
    return (f"✅ @{comment_author} is now away until {normalized_return_date}{reason_text}.\n\nYou'll be automatically added back to the queue on that date.{reassigned_msg}"), True


def handle_done_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    if assignment_request.is_pull_request:
        return "❌ `/done` is not supported on pull requests.", False
    labels = set(assignment_request.issue_labels)
    if CODING_GUIDELINE_LABEL in labels:
        return "❌ `/done` is not supported on coding guideline issues. Use `sign-off: create pr` when the review is ready.", False
    review_data = review_state.ensure_review_entry(state, issue_number)
    if review_data is None:
        return "❌ No active tracked review exists for this issue.", False
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    is_current_reviewer = len(current_assignees) == 1 and current_assignees[0].lower() == comment_author.lower()
    if not is_current_reviewer:
        permission_status = bot.github.get_user_permission_status(comment_author, "triage")
        if permission_status == "unavailable":
            return "❌ Unable to verify triage permissions right now; refusing to continue.", False
        if permission_status != "granted":
            return "❌ Only the current reviewer or a maintainer with triage+ permission can use `/done`.", False
    if not review_state.mark_review_complete(state, issue_number, comment_author, "command: /done"):
        return "ℹ️ This review is already marked complete.", True
    return "✅ Review marked complete.", True


def handle_label_command(
    bot,
    state: dict,
    issue_number: int,
    label_string: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    pattern = r'(?:(?<=^)|(?<=\s))([+-])(.+?)(?=\s[+-]|\s*$)'
    matches = re.findall(pattern, label_string)
    if not matches:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False, False
    existing_labels = bot.github.get_repo_labels()
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
            elif bot.github.add_label(issue_number, label):
                results.append(f"✅ Added label `{label}`")
                if (
                    label == "sign-off: create pr"
                    and not assignment_request.is_pull_request
                    and CODING_GUIDELINE_LABEL in set(assignment_request.issue_labels)
                ):
                    review_data = review_state.ensure_review_entry(state, issue_number)
                    reviewer = review_data.get("current_reviewer") if review_data else None
                    completion_changed = review_state.mark_review_complete(
                        state, issue_number, reviewer, "issue_label: sign-off: create pr"
                    )
                    state_changed = completion_changed or state_changed
            else:
                results.append(f"❌ Failed to add label `{label}`")
                all_success = False
        elif action == "-":
            if bot.github.remove_label(issue_number, label):
                results.append(f"✅ Removed label `{label}`")
            else:
                results.append(f"❌ Failed to remove label `{label}`")
                all_success = False
    if not results:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False, False
    return "\n".join(results), all_success, state_changed


def handle_sync_members_command(bot, state: dict) -> tuple[str, bool]:
    state, changes = bot.adapters.workflow.sync_members_with_queue(state)
    if changes:
        changes_text = "\n".join(f"- {change}" for change in changes)
        return f"✅ Queue synced with members.md:\n\n{changes_text}", True
    return "✅ Queue is already in sync with members.md.", True


def handle_queue_command(
    bot,
    state: dict,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    del request
    queue_size = len(state["queue"])
    github_repository = bot.get_config_value("GITHUB_REPOSITORY").strip()
    state_issue_number = bot.state_issue_number()
    state_issue_link = ""
    if github_repository and state_issue_number:
        state_issue_link = f"\n\n[View full state details](https://github.com/{github_repository}/issues/{state_issue_number})"
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
    return (f"ℹ️ **Available Commands**\n\n**Pass or step away:**\n- `{bot.BOT_MENTION} /pass [reason]` - Pass this review to next in queue (current reviewer only)\n- `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from queue until a date\n- `{bot.BOT_MENTION} /feedback` - Mark reviewer feedback ready for contributor follow-up\n- `{bot.BOT_MENTION} /release [reason]` - Release your current reviewer assignment\n\n**Assign reviewers:**\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Request the next reviewer from the queue\n- `{bot.BOT_MENTION} /claim` - Claim this review for yourself\n\n**Other:**\n- `{bot.BOT_MENTION} /done` - Mark a tracked non-PR issue review complete\n- `{bot.BOT_MENTION} /label +label-name` - Add a label\n- `{bot.BOT_MENTION} /label -label-name` - Remove a label\n- `{bot.BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub (current reviewer only)\n- `{bot.BOT_MENTION} /accept-no-fls-changes` - Update spec.lock and open a PR when no guidelines are impacted\n- `{bot.BOT_MENTION} /queue` - Show current queue status\n- `{bot.BOT_MENTION} /sync-members` - Sync queue with members.md"), True


def handle_claim_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    request: AssignmentRequest | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    is_producer = any(member["github"].lower() == comment_author.lower() for member in state["queue"])
    is_away = any(member["github"].lower() == comment_author.lower() for member in state.get("pass_until", []))
    if not is_producer and not is_away:
        return (f"❌ @{comment_author} is not in the reviewer queue. Only Producers can claim reviews."), False
    if is_away:
        return (f"❌ @{comment_author} is currently marked as away. Please use `{bot.BOT_MENTION} /away YYYY-MM-DD` to update your return date first, or wait until your scheduled return."), False
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    result = _apply_assignment_transition(
        bot,
        state,
        assignment_request,
        comment_author,
        "claim",
        current_assignees=current_assignees,
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    if not result.get("confirmed"):
        return _assignment_failure_response(comment_author, result, prefix=""), False, bool(
            result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
        )
    return f"✅ @{comment_author} has claimed this review{prev_text}.", True


def handle_release_command(
    bot,
    state: dict,
    issue_number: int,
    comment_author: str,
    args: list | None = None,
    request: AssignmentRequest | None = None,
    reviewer_authority: dict[str, object] | None = None,
) -> tuple[str, bool]:
    args = args or []
    request = request or build_assignment_request(bot, issue_number=issue_number)
    target_username = None
    reason = None
    if args and args[0].startswith("@"):
        target_username = args[0].lstrip("@")
        reason = " ".join(args[1:]) if len(args) > 1 else None
    else:
        target_username = comment_author
        reason = " ".join(args) if args else None
    issue_key = str(issue_number)
    assignment_method = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            assignment_method = issue_data.get("assignment_method")
    authority = reviewer_authority or assignment_flow.resolve_reviewer_command_authority(
        bot,
        state,
        request,
        actor=comment_author,
    )
    authority = assignment_flow.require_reviewer_command_actor(authority, comment_author)
    if not authority.get("authorized"):
        return _reviewer_command_authority_error("release", authority), False
    tracked_reviewer = str(authority["tracked_reviewer"])
    if target_username.lower() != tracked_reviewer.lower():
        return (f"❌ @{target_username} is not the current reviewer. Current reviewer: @{tracked_reviewer}"), False
    result = assignment_flow.confirm_reviewer_release(
        bot,
        state,
        request,
        reviewer=target_username,
        reposition_reviewer=assignment_method == "round-robin",
    )
    if not result.get("confirmed"):
        return _assignment_failure_response(target_username, result), False, bool(
            result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
        )
    reason_text = f" Reason: {reason}" if reason else ""
    return (f"✅ @{target_username} has released this review.{reason_text}\n\n_This issue/PR is now unassigned. Use `{bot.BOT_MENTION} /r? producers` to assign the next reviewer from the queue, or `{bot.BOT_MENTION} /claim` to claim it._"), True


def handle_assign_command(
    bot,
    state: dict,
    issue_number: int,
    username: str,
    request: AssignmentRequest | None = None,
    actor: str | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    username = username.lstrip("@")
    if not username:
        return (f"❌ Missing username. Usage: `{bot.BOT_MENTION} /r? @username`"), False
    actor = actor or bot.get_config_value("COMMENT_AUTHOR").strip()
    authorization = _assignment_command_authorization(
        bot,
        state,
        assignment_request,
        command_name=comment_command_policy.OrdinaryCommandId.ASSIGN_SPECIFIC.value,
        actor=actor,
        target=username,
    )
    if not authorization.authorized:
        return _assignment_authorization_failure("r?", authorization), False
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
    result = _apply_assignment_transition(
        bot,
        state,
        assignment_request,
        username,
        "manual",
        current_assignees=current_assignees,
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    if result.get("confirmed"):
        return f"✅ @{username} has been assigned as reviewer{prev_text}.", True
    return _assignment_failure_response(username, result), False, bool(
        result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
    )


def handle_assign_from_queue_command(
    bot,
    state: dict,
    issue_number: int,
    request: AssignmentRequest | None = None,
    actor: str | None = None,
) -> tuple[str, bool]:
    assignment_request = request or build_assignment_request(bot, issue_number=issue_number)
    actor = actor or bot.get_config_value("COMMENT_AUTHOR").strip()
    authorization = _assignment_command_authorization(
        bot,
        state,
        assignment_request,
        command_name=comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE.value,
        actor=actor,
        target="producers",
    )
    if not authorization.authorized:
        return _assignment_authorization_failure("r?", authorization), False
    current_assignees, assignee_error = _current_assignees_or_error(bot, issue_number)
    if assignee_error:
        return assignee_error, False
    skip_set = {assignment_request.issue_author} if assignment_request.issue_author else set()
    next_reviewer = bot.adapters.queue.get_next_reviewer(state, skip_usernames=skip_set)
    if not next_reviewer:
        return (f"❌ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue."), False
    result = _apply_assignment_transition(
        bot,
        state,
        assignment_request,
        next_reviewer,
        "round-robin",
        current_assignees=current_assignees,
    )
    prev_text = f" (previously: @{', @'.join(current_assignees)})" if current_assignees else ""
    if result.get("confirmed"):
        return f"✅ @{next_reviewer} (next in queue) has been assigned as reviewer{prev_text}.", True
    return _assignment_failure_response(next_reviewer, result), False, bool(
        result.get("diagnostic_changed") or result.get("cleared_current_reviewer")
    )
