"""Reviewer guidance text builders."""

from .config import BOT_MENTION


def get_assignment_failure_comment(reviewer: str, attempt, *, is_pull_request: bool) -> str | None:
    if attempt.status_code == 422:
        if is_pull_request:
            return (
                "@{reviewer} is designated as reviewer by queue rotation, but GitHub could not add them to PR "
                "Reviewers automatically (API 422). A triage+ approver may still be required before merge queue."
            ).format(reviewer=reviewer)
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not "
            "add them as an assignee automatically (API 422)."
        )
    if attempt.exhausted_retryable_failure:
        target = "PR Reviewers" if is_pull_request else "issue assignees"
        suffix = " A triage+ approver may still be required before merge queue." if is_pull_request else ""
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not add them to "
            f"{target} automatically after retries (status {attempt.status_code}).{suffix}"
        )
    return None


def get_issue_guidance(reviewer: str, issue_author: str) -> str:
    """Generate guidance text for an issue reviewer."""
    return f"""👋 Hey @{reviewer}! You've been assigned to review this coding guideline issue.

## Your Role as Reviewer

As outlined in our [contribution guide](CONTRIBUTING.md), please:

1. **Provide initial feedback within 14 days**
2. **Work with @{issue_author}** to flesh out the concept and ensure the guideline is well-prepared for a Pull Request
3. **Check the prerequisites** before the issue is ready to become a PR:
   - The new rule isn't already covered by another rule
   - All sections contain some content
   - Content written may be *incomplete*, but must not be *incorrect*
   - The `🧪 Code Example Test Results` section shows all example code compiles

4. When ready, **add the `sign-off: create pr` label** to signal the contributor should create a PR

## Bot Commands

If you need to pass this review:
- `{BOT_MENTION} /pass [reason]` - Pass just this issue to the next reviewer
- `{BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} /release [@username] [reason]` - Release assignment (yours or someone else's with triage+ permission)

To assign someone else:
- `{BOT_MENTION} /r? @username` - Assign a specific reviewer
- `{BOT_MENTION} /r? producers` - Request the next reviewer from the queue

Other commands:
- `{BOT_MENTION} /claim` - Claim this review for yourself
- `{BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub
- `{BOT_MENTION} /label +label-name` - Add a label
- `{BOT_MENTION} /label -label-name` - Remove a label
- `{BOT_MENTION} /queue` - Show reviewer queue
- `{BOT_MENTION} /commands` - Show all available commands
"""


def get_fls_audit_guidance(reviewer: str, issue_author: str) -> str:
    """Generate guidance text for an FLS audit issue reviewer."""
    return f"""👋 Hey @{reviewer}! You've been assigned to review this FLS audit issue.

## Your Role as Reviewer

Please review the audit report in the issue body and determine whether any
guideline changes are required.

If the changes do **not** affect any guidelines:
- Comment `{BOT_MENTION} /accept-no-fls-changes` to open a PR that updates `src/spec.lock`.

If the changes **do** affect guidelines:
- Open a PR with the necessary guideline updates and reference this issue.

## Bot Commands

If you need to pass this review:
- `{BOT_MENTION} /pass [reason]` - Pass just this issue to the next reviewer
- `{BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} /release [@username] [reason]` - Release assignment (yours or someone else's with triage+ permission)

To assign someone else:
- `{BOT_MENTION} /r? @username` - Assign a specific reviewer
- `{BOT_MENTION} /r? producers` - Request the next reviewer from the queue

Other commands:
- `{BOT_MENTION} /claim` - Claim this review for yourself
- `{BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub
- `{BOT_MENTION} /label +label-name` - Add a label
- `{BOT_MENTION} /label -label-name` - Remove a label
- `{BOT_MENTION} /queue` - Show reviewer queue
- `{BOT_MENTION} /commands` - Show all available commands
"""


def get_pr_guidance(reviewer: str, pr_author: str) -> str:
    """Generate guidance text for a PR reviewer."""
    return f"""👋 Hey @{reviewer}! You've been assigned to review this coding guideline PR.

## Your Role as Reviewer

As outlined in our [contribution guide](CONTRIBUTING.md), please:

1. **Begin your review within 14 days**
2. **Provide constructive feedback** on the guideline content, examples, and formatting
3. **Iterate with @{pr_author}** - they may update the PR based on your feedback
4. When the guideline is ready, **approve and add to the merge queue**

## Review Checklist

- [ ] Guideline title is clear and follows conventions
- [ ] Amplification section expands on the title appropriately
- [ ] Rationale explains the "why" effectively
- [ ] Non-compliant example(s) clearly show the problem
- [ ] Compliant example(s) clearly show the solution
- [ ] Code examples compile (check the CI results)
- [ ] FLS paragraph ID is correct

## Bot Commands

If you need to pass this review:
- `{BOT_MENTION} /pass [reason]` - Pass just this PR to the next reviewer
- `{BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} /release [@username] [reason]` - Release assignment (yours or someone else's with triage+ permission)

To assign someone else:
- `{BOT_MENTION} /r? @username` - Assign a specific reviewer
- `{BOT_MENTION} /r? producers` - Request the next reviewer from the queue

Other commands:
- `{BOT_MENTION} /claim` - Claim this review for yourself
- `{BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub
- `{BOT_MENTION} /label +label-name` - Add a label
- `{BOT_MENTION} /label -label-name` - Remove a label
- `{BOT_MENTION} /queue` - Show reviewer queue
- `{BOT_MENTION} /commands` - Show all available commands
"""
