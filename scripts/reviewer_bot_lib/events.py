"""Reviewer-bot event and reconciliation handlers."""

import json
import os
from datetime import datetime, timezone


def get_latest_review_by_reviewer(bot, reviews: list[dict], reviewer: str) -> dict | None:
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), -1)
    for index, review in enumerate(reviews):
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            submitted_at = datetime.min.replace(tzinfo=timezone.utc)
        review_key = (submitted_at, index)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review
    return latest_review


def find_triage_approval_after(bot, reviews: list[dict], since: datetime | None) -> tuple[str, datetime] | None:
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[datetime, int, str]] = []
    for index, review in enumerate(reviews):
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, index, author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at
    return None


def reconcile_active_review_entry(bot, state: dict, issue_number: int, *, require_pull_request_context: bool = True, completion_source: str = "rectify:reconcile-pr-review") -> tuple[str, bool, bool]:
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False
    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.", True, False
    if review_data.get("review_completed_at") and not review_data.get("mandatory_approver_required"):
        return f"ℹ️ Review for #{issue_number} is already marked complete; no changes made.", True, False
    if require_pull_request_context:
        is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
        if not is_pr:
            return f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only reconciles PR reviews.", True, False
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False
    state_changed = False
    messages: list[str] = []
    latest_review = bot.get_latest_review_by_reviewer(reviews, assigned_reviewer)
    if latest_review is None:
        messages.append(f"No review by assigned reviewer @{assigned_reviewer} was found on PR #{issue_number}.")
    else:
        latest_state = str(latest_review.get("state", "")).upper()
        if latest_state == "APPROVED":
            changed = bot.handle_pr_approved_review(state, issue_number, assigned_reviewer, completion_source)
            if changed:
                state_changed = True
                messages.append(f"latest review by @{assigned_reviewer} is `APPROVED`; applied approval transitions")
            else:
                messages.append(f"latest review by @{assigned_reviewer} is `APPROVED`, but state already reflected it")
        elif latest_state in {"COMMENTED", "CHANGES_REQUESTED"}:
            changed = bot.update_reviewer_activity(state, issue_number, assigned_reviewer)
            if changed:
                state_changed = True
                messages.append(f"latest review by @{assigned_reviewer} is `{latest_state}`; refreshed reviewer activity")
            else:
                messages.append(f"latest assigned-reviewer state is `{latest_state}` and no update was needed")
        else:
            state_name = latest_state or "UNKNOWN"
            messages.append(f"latest review by @{assigned_reviewer} is `{state_name}` and no reconciliation transition applies")
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data and review_data.get("mandatory_approver_required"):
        escalation_opened_at = bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at")) or bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        triage_approval = find_triage_approval_after(bot, reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if bot.satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")
    if state_changed:
        detail = "; ".join(messages) if messages else "applied state reconciliation transitions"
        return f"✅ Rectified PR #{issue_number}: {detail}.", True, True
    detail = "; ".join(messages) if messages else "no reconciliation transitions applied"
    return f"ℹ️ Rectify checked PR #{issue_number}: {detail}.", True, False


def handle_transition_notice(bot, state: dict, issue_number: int, reviewer: str) -> bool:
    notice_message = f"""🔔 **Transition Period Ended**

@{reviewer}, the {bot.TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

**The review will now be reassigned to the next person in the queue.**

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    bot.post_comment(issue_number, notice_message)
    print(f"Posted transition notice for #{issue_number} to @{reviewer}")
    return True


def handle_issue_or_pr_opened(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_or_pr_opened")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False
    print(f"Processing opened event for #{issue_number}")
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    current_assignees = bot.get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers/assignees: {current_assignees}")
        return False
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    print(f"ISSUE_LABELS env: {labels_json}")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        print("Failed to parse ISSUE_LABELS as JSON")
        labels = []
    if not any(label in bot.REVIEW_LABELS for label in labels):
        print(f"Issue #{issue_number} does not have review labels {sorted(bot.REVIEW_LABELS)} (labels: {labels})")
        return False
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()
    reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
    if not reviewer:
        bot.post_comment(issue_number, f"⚠️ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue.")
        return False
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = bot.request_reviewer_assignment(issue_number, reviewer)
    bot.set_current_reviewer(state, issue_number, reviewer)
    bot.record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")
    failure_comment = bot.get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        bot.post_comment(issue_number, failure_comment)
    if is_pr:
        if assignment_attempt.success:
            guidance = bot.get_pr_guidance(reviewer, issue_author)
            bot.post_comment(issue_number, guidance)
    else:
        guidance = bot.get_fls_audit_guidance(reviewer, issue_author) if bot.FLS_AUDIT_LABEL in labels else bot.get_issue_guidance(reviewer, issue_author)
        bot.post_comment(issue_number, guidance)
    return True


def handle_labeled_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_labeled_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False
    label_name = os.environ.get("LABEL_NAME", "")
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    bot.collect_touched_item(issue_number)
    if label_name == "sign-off: create pr":
        if is_pr:
            print("Sign-off label applied to PR; ignoring")
            return False
        review_data = bot.ensure_review_entry(state, issue_number)
        reviewer = review_data.get("current_reviewer") if review_data else None
        return bot.mark_review_complete(state, issue_number, reviewer, "issue_label: sign-off: create pr")
    if label_name not in bot.REVIEW_LABELS:
        print(f"Label '{label_name}' is not a review label, skipping")
        return False
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    current_assignees = bot.get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers: {current_assignees}")
        return False
    print(f"Processing labeled event for #{issue_number}, author: {os.environ.get('ISSUE_AUTHOR', '')}")
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()
    reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
    print(f"Selected reviewer for #{issue_number}: {reviewer}")
    if not reviewer:
        bot.post_comment(issue_number, f"⚠️ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue.")
        return False
    assignment_attempt = bot.request_reviewer_assignment(issue_number, reviewer)
    bot.set_current_reviewer(state, issue_number, reviewer)
    bot.record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")
    failure_comment = bot.get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        bot.post_comment(issue_number, failure_comment)
    if is_pr:
        if assignment_attempt.success:
            guidance = bot.get_pr_guidance(reviewer, issue_author)
            bot.post_comment(issue_number, guidance)
    else:
        guidance = bot.get_fls_audit_guidance(reviewer, issue_author) if label_name == bot.FLS_AUDIT_LABEL else bot.get_issue_guidance(reviewer, issue_author)
        bot.post_comment(issue_number, guidance)
    return True


def handle_pull_request_review_event(bot, state: dict) -> bool:
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False
    review_state = os.environ.get("REVIEW_STATE", "").strip().upper()
    review_author = os.environ.get("REVIEW_AUTHOR", "").strip()
    if not review_state or not review_author:
        print("Missing review context")
        return False
    bot.collect_touched_item(issue_number)
    review_action = os.environ.get("EVENT_ACTION", "").strip().lower()
    is_cross_repo = os.environ.get("PR_IS_CROSS_REPOSITORY", "false").lower() == "true"
    if is_cross_repo:
        print(
            f"Deferring cross-repo pull_request_review reconciliation for #{issue_number}: this event may have read-only permissions. A trusted workflow_run reconcile will persist state after this run succeeds. If needed, use `@guidelines-bot /rectify` as manual fallback."
        )
        return False
    bot.assert_lock_held("handle_pull_request_review_event")
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        print(f"No active review entry for #{issue_number}")
        return False
    current_reviewer = review_data.get("current_reviewer")
    if review_action == "dismissed" or review_state == "DISMISSED":
        print(f"Observed dismissed review on #{issue_number}; deferring to status-label projection")
        return False
    if review_state == "APPROVED":
        return bot.handle_pr_approved_review(state, issue_number, review_author, "pull_request_review")
    if review_state in {"COMMENTED", "CHANGES_REQUESTED"}:
        if not current_reviewer or current_reviewer.lower() != review_author.lower():
            print(f"Ignoring review from @{review_author} on #{issue_number}; current reviewer is @{current_reviewer}")
            return False
        return bot.update_reviewer_activity(state, issue_number, review_author)
    print(f"Ignoring review state '{review_state}' for #{issue_number}")
    return False


def handle_workflow_run_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_workflow_run_event")
    workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
    workflow_run_event_action = os.environ.get("WORKFLOW_RUN_EVENT_ACTION", "").strip().lower()
    if workflow_run_event != "pull_request_review":
        observed = workflow_run_event or "<missing>"
        print(f"Ignoring workflow_run reconcile event with unsupported source event: {observed}")
        return False
    if workflow_run_event_action not in {"submitted", "dismissed"}:
        observed = workflow_run_event_action or "<missing>"
        print(f"Ignoring workflow_run reconcile event with unsupported source action: {observed}")
        return False
    issue_number = bot.resolve_workflow_run_pr_number()
    bot.collect_touched_item(issue_number)
    if workflow_run_event_action == "dismissed":
        print(f"Workflow_run observed dismissed review for #{issue_number}; projecting labels only")
        return False
    message, success, state_changed = bot.reconcile_active_review_entry(state, issue_number, require_pull_request_context=False, completion_source="workflow_run:pull_request_review")
    print(message)
    if not success:
        raise RuntimeError(f"Workflow_run reconcile failed for pull request #{issue_number}: {message}")
    if state_changed and not bot.post_comment(issue_number, message):
        print(f"WARNING: Workflow_run reconcile changed state but failed to post comment on pull request #{issue_number}.", file=bot.sys.stderr)
    return state_changed


def handle_closed_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_closed_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found for closed event")
        return False
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        print(f"Cleaned up active_reviews entry for #{issue_number}")
        return True
    print(f"No active_reviews entry found for #{issue_number}")
    return False


def handle_comment_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_comment_event")
    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_id = os.environ.get("COMMENT_ID", "")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not comment_body or not issue_number:
        return False
    activity_updated = bot.update_reviewer_activity(state, issue_number, comment_author)
    sanitized_body = bot.strip_code_blocks(comment_body)
    parsed = bot.parse_command(sanitized_body)
    if not parsed:
        return activity_updated
    command, args = parsed
    print(f"Parsed command: {command}, args: {args}")
    response = ""
    success = False
    state_changed = False
    status_projection_commands = {"pass", "away", "claim", "release", "rectify", "r?-user", "assign-from-queue"}
    if command == "_multiple_commands":
        response = f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. For a list of commands, use `{bot.BOT_MENTION} /commands`."
    elif command == "pass":
        reason = " ".join(args) if args else None
        response, success = bot.handle_pass_command(state, issue_number, comment_author, reason)
        state_changed = success
    elif command == "away":
        if not args:
            response = f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`"
        else:
            return_date = args[0]
            reason = " ".join(args[1:]) if len(args) > 1 else None
            response, success = bot.handle_pass_until_command(state, issue_number, comment_author, return_date, reason)
            state_changed = success
    elif command == "label":
        if not args:
            response = f"❌ Missing label. Usage: `{bot.BOT_MENTION} /label +label-name` or `{bot.BOT_MENTION} /label -label-name`"
        else:
            full_arg = " ".join(args)
            response, success = bot.handle_label_command(issue_number, full_arg)
    elif command == "accept-no-fls-changes":
        response, success = bot.handle_accept_no_fls_changes_command(issue_number, comment_author)
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
        response, success = bot.handle_release_command(state, issue_number, comment_author, args)
        state_changed = success
    elif command == "rectify":
        response, success, state_changed = bot.handle_rectify_command(state, issue_number, comment_author)
    elif command == "r?-user":
        username = args[0] if args else ""
        response, success = bot.handle_assign_command(state, issue_number, username)
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
    if command in status_projection_commands:
        bot.collect_touched_item(issue_number)
    if comment_id and command != "_multiple_commands":
        bot.add_reaction(int(comment_id), "eyes")
        if success:
            bot.add_reaction(int(comment_id), "+1")
    if response:
        bot.post_comment(issue_number, response)
    return state_changed


def handle_manual_dispatch(bot, state: dict) -> bool:
    action = os.environ.get("MANUAL_ACTION", "")
    if action == "show-state":
        print(f"Current state:\n{bot.yaml.dump(state, default_flow_style=False)}")
        return False
    bot.assert_lock_held("handle_manual_dispatch")
    if action == "sync-members":
        state, changes = bot.sync_members_with_queue(state)
        if changes:
            print(f"Sync changes: {changes}")
        return True
    if action == "repair-review-status-labels":
        tracked_numbers = []
        active_reviews = state.get("active_reviews", {})
        if isinstance(active_reviews, dict):
            for issue_key in active_reviews:
                try:
                    tracked_numbers.append(int(issue_key))
                except (TypeError, ValueError):
                    continue
        for issue_number in tracked_numbers:
            bot.collect_touched_item(issue_number)
        for issue_number in bot.list_open_items_with_status_labels():
            bot.collect_touched_item(issue_number)
        print(f"Collected {len(bot.TOUCHED_ISSUE_NUMBERS)} item(s) for status-label repair")
        return False
    if action == "check-overdue":
        return bot.handle_scheduled_check(state)
    return False


def handle_scheduled_check(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_scheduled_check")
    print("Running scheduled check for overdue reviews...")
    overdue_reviews = bot.check_overdue_reviews(state)
    if not overdue_reviews:
        print("No overdue reviews found.")
        return False
    print(f"Found {len(overdue_reviews)} overdue review(s)")
    state_changed = False
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        if review["needs_warning"]:
            print(f"Sending warning for #{issue_number} to @{reviewer} ({review['days_overdue']} days overdue)")
            if bot.handle_overdue_review_warning(state, issue_number, reviewer):
                state_changed = True
        elif review["needs_transition"]:
            print(f"Transition period ended for #{issue_number}, @{reviewer} ({review['days_since_warning']} days since warning)")
            bot.handle_transition_notice(state, issue_number, reviewer)
            issue_key = str(issue_number)
            review_data = state["active_reviews"].get(issue_key, {})
            skipped = review_data.get("skipped", [])
            skip_set = set(skipped) | {reviewer}
            next_reviewer = bot.get_next_reviewer(state, skip_usernames=skip_set)
            if next_reviewer:
                bot.unassign_reviewer(issue_number, reviewer)
                assignment_attempt = bot.request_reviewer_assignment(issue_number, next_reviewer)
                bot.set_current_reviewer(state, issue_number, next_reviewer)
                if issue_key in state["active_reviews"] and reviewer not in state["active_reviews"][issue_key].get("skipped", []):
                    state["active_reviews"][issue_key]["skipped"].append(reviewer)
                failure_comment = bot.get_assignment_failure_comment(next_reviewer, assignment_attempt)
                if failure_comment:
                    bot.post_comment(issue_number, failure_comment)
                guidance = bot.get_issue_guidance(next_reviewer, "the contributor")
                bot.post_comment(issue_number, guidance)
                bot.record_assignment(state, next_reviewer, issue_number, "issue")
                print(f"Reassigned #{issue_number} from @{reviewer} to @{next_reviewer}")
            else:
                print(f"No available reviewers to reassign #{issue_number}")
            bot.collect_touched_item(issue_number)
            state_changed = True
    return state_changed
