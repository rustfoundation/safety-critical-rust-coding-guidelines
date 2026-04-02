"""Overdue review domain logic for reviewer-bot."""

from __future__ import annotations


def check_overdue_reviews(bot, state: dict) -> list[dict]:
    """Check all active reviews for overdue ones."""
    if "active_reviews" not in state:
        return []

    now = bot.datetime.now(bot.timezone.utc)
    overdue = []

    for issue_key, review_data in state["active_reviews"].items():
        if not isinstance(review_data, dict):
            continue

        if review_data.get("review_completed_at"):
            continue

        if review_data.get("transition_notice_sent_at"):
            continue

        current_reviewer = review_data.get("current_reviewer")
        if not current_reviewer:
            continue

        issue_number = int(issue_key)
        issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
        if not isinstance(issue_snapshot, dict):
            print(f"WARNING: Skipping overdue evaluation for #{issue_number}; issue/PR snapshot unavailable")
            continue
        if isinstance(issue_snapshot.get("pull_request"), dict):
            response_state = bot.compute_reviewer_response_state(
                issue_number,
                review_data,
                issue_snapshot=issue_snapshot,
            )
            if response_state.get("state") != "awaiting_reviewer_response":
                continue
            last_activity = response_state.get("anchor_timestamp")
        else:
            last_activity = review_data.get("last_reviewer_activity")
            if not last_activity:
                last_activity = review_data.get("assigned_at")

        if not last_activity:
            continue

        try:
            last_activity_dt = bot.datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        days_since_activity = (now - last_activity_dt).days

        if days_since_activity < bot.REVIEW_DEADLINE_DAYS:
            continue

        transition_warning_sent = review_data.get("transition_warning_sent")
        if transition_warning_sent:
            try:
                warning_dt = bot.datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
                days_since_warning = (now - warning_dt).days

                if days_since_warning >= bot.TRANSITION_PERIOD_DAYS:
                    overdue.append(
                        {
                            "issue_number": issue_number,
                            "reviewer": current_reviewer,
                            "days_overdue": days_since_activity,
                            "days_since_warning": days_since_warning,
                            "needs_warning": False,
                            "needs_transition": True,
                        }
                    )
            except (ValueError, AttributeError):
                pass
        else:
            overdue.append(
                {
                    "issue_number": issue_number,
                    "reviewer": current_reviewer,
                    "days_overdue": days_since_activity - bot.REVIEW_DEADLINE_DAYS,
                    "days_since_warning": 0,
                    "needs_warning": True,
                    "needs_transition": False,
                }
            )

    return overdue


def find_existing_transition_notice(bot, issue_number: int, transition_warning_sent: str | None) -> str | None:
    if not isinstance(transition_warning_sent, str) or not transition_warning_sent:
        return None
    try:
        warning_dt = bot.datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    response = bot.github_api("GET", f"issues/{issue_number}/comments?per_page=100")
    if not isinstance(response, list):
        return None
    first_match = None
    for comment in response:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        created_at = comment.get("created_at")
        body = comment.get("body")
        if not isinstance(login, str) or not isinstance(created_at, str) or not isinstance(body, str):
            continue
        if login != "github-actions[bot]":
            continue
        first_line = body.splitlines()[0].strip() if body.splitlines() else ""
        if first_line != "🔔 **Transition Period Ended**":
            continue
        try:
            created_dt = bot.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if created_dt < warning_dt:
            continue
        if first_match is None or created_dt < first_match[0]:
            first_match = (created_dt, created_at)
    return first_match[1] if first_match else None


def backfill_transition_notice_if_present(bot, state: dict, issue_number: int) -> bool:
    issue_key = str(issue_number)
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    review_data = active_reviews.get(issue_key)
    if not isinstance(review_data, dict):
        return False
    if review_data.get("transition_notice_sent_at"):
        return False
    existing_notice = find_existing_transition_notice(bot, issue_number, review_data.get("transition_warning_sent"))
    if not existing_notice:
        return False
    review_data["transition_notice_sent_at"] = existing_notice
    return True


def handle_overdue_review_warning(bot, state: dict, issue_number: int, reviewer: str) -> bool:
    """Post a warning comment and record that we've warned the reviewer."""
    issue_key = str(issue_number)

    if "active_reviews" not in state or issue_key not in state["active_reviews"]:
        return False

    review_data = state["active_reviews"][issue_key]
    if not isinstance(review_data, dict):
        return False

    warning_message = f"""⚠️ **Review Reminder**

Hey @{reviewer}, it's been more than {bot.REVIEW_DEADLINE_DAYS} days since you were assigned to review this.

**Please take one of the following actions:**

1. **Begin your review** - Post a comment with your feedback
2. **Pass the review** - Use `{bot.BOT_MENTION} /pass [reason]` to assign the next reviewer
3. **Step away temporarily** - Use `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]` if you need time off

If no action is taken within {bot.TRANSITION_PERIOD_DAYS} days, you may be transitioned from Producer to Observer status per our [contribution guidelines](CONTRIBUTING.md#review-deadlines).

_Life happens! If you're dealing with something, just let us know._"""

    if not bot.post_comment(issue_number, warning_message):
        return False

    now = bot.datetime.now(bot.timezone.utc).isoformat()
    review_data["transition_warning_sent"] = now

    print(f"Posted overdue warning for #{issue_number} to @{reviewer}")
    return True
