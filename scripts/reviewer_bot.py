#!/usr/bin/env python3
"""
Reviewer Bot for Safety-Critical Rust Coding Guidelines

This bot manages round-robin assignment of reviewers for coding guideline
issues and PRs. It supports commands for passing reviews, vacations, and
label management.

All commands must be prefixed with @guidelines-bot:

  @guidelines-bot pass! [reason]
    - Skip the assigned reviewer for this issue/PR and assign the next person
    - The skipped reviewer stays in queue position for future assignments

  @guidelines-bot pass-until! YYYY-MM-DD [reason]
    - Remove yourself from the queue until the specified date
    - Automatically assigns the next available reviewer

  @guidelines-bot claim
    - Assign yourself as the reviewer for this issue/PR
    - Removes any existing reviewer assignment

  @guidelines-bot release
    - Release your assignment from this issue/PR
    - The next person in the queue will be assigned

  @guidelines-bot assign @username
    - Assign a specific person as the reviewer

  @guidelines-bot r? @username
    - Shorthand to assign a specific reviewer

  @guidelines-bot r? producers
    - Assign the next reviewer from the round-robin queue
    - Useful for requesting a reviewer on an already-open issue/PR

  @guidelines-bot label +label-name
    - Add a label to the issue/PR

  @guidelines-bot label -label-name
    - Remove a label from the issue/PR

  @guidelines-bot sync-members
    - Manually trigger sync of the queue with members.md

  @guidelines-bot queue-status
    - Show current queue status and who's next up
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import yaml

# GitHub API interaction
try:
    import requests
except ImportError:
    # requests is available via uv
    pass


# ==============================================================================
# Configuration
# ==============================================================================

BOT_NAME = "guidelines-bot"
BOT_MENTION = f"@{BOT_NAME}"
CODING_GUIDELINE_LABEL = "coding guideline"
# State is stored in a dedicated GitHub issue body (set via environment variable)
STATE_ISSUE_NUMBER = int(os.environ.get("STATE_ISSUE_NUMBER", "0"))
# Members file is in the consortium repo, not this repo
MEMBERS_URL = "https://raw.githubusercontent.com/rustfoundation/safety-critical-rust-consortium/main/subcommittee/coding-guidelines/members.md"
MAX_RECENT_ASSIGNMENTS = 20


# ==============================================================================
# GitHub API Helpers
# ==============================================================================


def get_github_token() -> str:
    """Get the GitHub token from environment."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return token


def github_api(method: str, endpoint: str, data: dict | None = None) -> dict | None:
    """Make a GitHub API request."""
    token = get_github_token()
    repo = f"{os.environ['REPO_OWNER']}/{os.environ['REPO_NAME']}"
    url = f"https://api.github.com/repos/{repo}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.request(method, url, headers=headers, json=data)

    if response.status_code >= 400:
        print(f"GitHub API error: {response.status_code} - {response.text}", file=sys.stderr)
        return None

    if response.content:
        return response.json()
    return {}


def post_comment(issue_number: int, body: str) -> bool:
    """Post a comment on an issue or PR."""
    result = github_api("POST", f"issues/{issue_number}/comments", {"body": body})
    return result is not None


def add_label(issue_number: int, label: str) -> bool:
    """Add a label to an issue or PR."""
    result = github_api("POST", f"issues/{issue_number}/labels", {"labels": [label]})
    return result is not None


def remove_label(issue_number: int, label: str) -> bool:
    """Remove a label from an issue or PR."""
    _result = github_api("DELETE", f"issues/{issue_number}/labels/{label}")
    # 404 is ok - label might not exist
    return True


def assign_reviewer(issue_number: int, username: str) -> bool:
    """Assign a user as a reviewer (via assignees for issues, reviewers for PRs)."""
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"

    if is_pr:
        # For PRs, request review
        result = github_api("POST", f"pulls/{issue_number}/requested_reviewers",
                          {"reviewers": [username]})
    else:
        # For issues, use assignees
        result = github_api("POST", f"issues/{issue_number}/assignees",
                          {"assignees": [username]})

    return result is not None


def get_issue_assignees(issue_number: int) -> list[str]:
    """Get current reviewers for an issue/PR.
    
    For issues: returns assignees
    For PRs: returns only requested_reviewers (NOT assignees, as those are typically the author)
    """
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    
    if is_pr:
        # For PRs, ONLY check requested_reviewers (assignees are typically the author)
        result = github_api("GET", f"pulls/{issue_number}")
        if result and "requested_reviewers" in result:
            return [r["login"] for r in result["requested_reviewers"]]
    else:
        # For issues, check assignees
        result = github_api("GET", f"issues/{issue_number}")
        if result and "assignees" in result:
            return [a["login"] for a in result["assignees"]]
    
    return []


def add_reaction(comment_id: int, reaction: str) -> bool:
    """Add a reaction to a comment."""
    result = github_api("POST", f"issues/comments/{comment_id}/reactions",
                       {"content": reaction})
    return result is not None


def remove_assignee(issue_number: int, username: str) -> bool:
    """Remove a user from assignees."""
    result = github_api("DELETE", f"issues/{issue_number}/assignees",
                       {"assignees": [username]})
    return result is not None


def remove_pr_reviewer(issue_number: int, username: str) -> bool:
    """Remove a requested reviewer from a PR."""
    result = github_api("DELETE", f"pulls/{issue_number}/requested_reviewers",
                       {"reviewers": [username]})
    return result is not None


def unassign_reviewer(issue_number: int, username: str) -> bool:
    """Remove a user as reviewer (handles both issues and PRs)."""
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"

    if is_pr:
        # For PRs, remove from requested reviewers
        remove_pr_reviewer(issue_number, username)
    
    # Always try to remove from assignees (works for both)
    return remove_assignee(issue_number, username)


# ==============================================================================
# Members Parsing
# ==============================================================================


def fetch_members() -> list[dict]:
    """
    Fetch and parse members.md from the consortium repo to extract Producers.

    Returns a list of dicts with 'github' and 'name' keys.
    """
    try:
        response = requests.get(MEMBERS_URL, timeout=10)
        response.raise_for_status()
        content = response.text
    except requests.RequestException as e:
        print(f"WARNING: Failed to fetch members file from {MEMBERS_URL}: {e}", file=sys.stderr)
        return []

    producers = []

    # Find the table in the markdown
    lines = content.split("\n")
    in_table = False
    headers = []

    for line in lines:
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Check if this is a table row
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]

            # Check if this is the header row
            if not in_table and "Member Name" in cells:
                headers = [h.lower().replace(" ", "_") for h in cells]
                in_table = True
                continue

            # Skip separator row
            if in_table and all(c.replace("-", "").replace(":", "") == "" for c in cells):
                continue

            # Parse data row
            if in_table and len(cells) == len(headers):
                row = dict(zip(headers, cells))

                # Check if this is a Producer (role contains "Producer" anywhere)
                role = row.get("role", "").strip()
                if "Producer" in role:
                    github_username = row.get("github_username", "").strip()
                    # Remove @ prefix if present
                    if github_username.startswith("@"):
                        github_username = github_username[1:]

                    if github_username:
                        producers.append({
                            "github": github_username,
                            "name": row.get("member_name", "").strip(),
                        })

    return producers


# ==============================================================================
# State Management
# ==============================================================================


def get_state_issue() -> dict | None:
    """Fetch the state issue from GitHub."""
    if not STATE_ISSUE_NUMBER:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return None
    
    return github_api("GET", f"issues/{STATE_ISSUE_NUMBER}")


def parse_state_from_issue(issue: dict) -> dict:
    """Parse YAML state from issue body."""
    body = issue.get("body", "") or ""
    
    # Extract YAML from code block if present
    yaml_match = re.search(r"```ya?ml\n(.*?)\n```", body, re.DOTALL)
    if yaml_match:
        yaml_content = yaml_match.group(1)
    else:
        # Try to parse the whole body as YAML
        yaml_content = body
    
    try:
        state = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as e:
        print(f"WARNING: Failed to parse state YAML: {e}", file=sys.stderr)
        state = {}
    
    return state


def load_state() -> dict:
    """Load the current state from the state issue."""
    default_state = {
        "last_updated": None,
        "current_index": 0,
        "queue": [],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},  # Tracks review state per issue/PR: {number: {skipped: [], current_reviewer: str}}
    }
    
    issue = get_state_issue()
    if not issue:
        print("WARNING: Could not fetch state issue, using defaults", file=sys.stderr)
        return default_state
    
    state = parse_state_from_issue(issue)
    
    # Ensure all required keys exist AND are not None
    # (YAML parses empty values as None, not as empty lists)
    if state.get("last_updated") is None:
        state["last_updated"] = None  # This one can be None
    if not isinstance(state.get("current_index"), int):
        state["current_index"] = 0
    if not isinstance(state.get("queue"), list):
        state["queue"] = []
    if not isinstance(state.get("pass_until"), list):
        state["pass_until"] = []
    if not isinstance(state.get("recent_assignments"), list):
        state["recent_assignments"] = []
    if not isinstance(state.get("active_reviews"), dict):
        state["active_reviews"] = {}

    return state


def save_state(state: dict) -> bool:
    """Save the state to the state issue. Returns True on success."""
    if not STATE_ISSUE_NUMBER:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return False
    
    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Format the issue body with YAML in a code block
    yaml_content = yaml.dump(state, default_flow_style=False, sort_keys=False,
                            allow_unicode=True)
    
    body = f"""## 📊 Reviewer Bot State

> ⚠️ **DO NOT EDIT MANUALLY** - This issue is automatically maintained by the reviewer bot.
> Use bot commands instead (see [CONTRIBUTING.md](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/blob/main/CONTRIBUTING.md) for details).

This issue tracks the round-robin assignment of reviewers for coding guidelines.

### Current State

```yaml
{yaml_content}```

### What This Tracks

- **queue**: Active reviewers in rotation order
- **current_index**: Position in queue (who's next)
- **pass_until**: Reviewers temporarily away with return dates
- **recent_assignments**: Last {MAX_RECENT_ASSIGNMENTS} assignments for visibility
- **active_reviews**: Per-issue/PR tracking of who passed and the current designated reviewer
"""

    result = github_api("PATCH", f"issues/{STATE_ISSUE_NUMBER}", {"body": body})
    if result:
        print(f"State saved to issue #{STATE_ISSUE_NUMBER}")
        return True
    else:
        print(f"ERROR: Failed to save state to issue #{STATE_ISSUE_NUMBER}", file=sys.stderr)
        return False


def sync_members_with_queue(state: dict) -> tuple[dict, list[str]]:
    """
    Sync the queue with the current members.md file from the consortium repo.

    Returns the updated state and a list of changes made.
    """
    producers = fetch_members()
    current_queue = {m["github"]: m for m in state["queue"]}
    pass_until_users = {m["github"] for m in state.get("pass_until", [])}

    changes = []

    # Find new producers to add
    for producer in producers:
        github = producer["github"]
        if github not in current_queue and github not in pass_until_users:
            state["queue"].append(producer)
            changes.append(f"Added {github} to queue")

    # Find removed producers
    current_producer_usernames = {p["github"] for p in producers}
    state["queue"] = [
        m for m in state["queue"]
        if m["github"] in current_producer_usernames
    ]

    # Also clean up pass_until for removed producers
    removed_from_queue = [
        m["github"] for m in current_queue.values()
        if m["github"] not in current_producer_usernames
    ]
    for username in removed_from_queue:
        changes.append(f"Removed {username} from queue (no longer a Producer)")

    # Update names in case they changed
    producer_names = {p["github"]: p["name"] for p in producers}
    for member in state["queue"]:
        if member["github"] in producer_names:
            member["name"] = producer_names[member["github"]]

    # Ensure current_index is valid
    if state["queue"]:
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0

    return state, changes


def process_pass_until_expirations(state: dict) -> tuple[dict, list[str]]:
    """
    Check for expired pass-until entries and restore them to the queue.

    Returning members are inserted right after the current index,
    so they're next up in rotation.

    Returns the updated state and a list of users restored.
    """
    now = datetime.now(timezone.utc).date()
    restored = []
    still_away = []

    for entry in state.get("pass_until", []):
        return_date = entry.get("return_date")
        if return_date:
            if isinstance(return_date, str):
                try:
                    return_date = datetime.strptime(return_date, "%Y-%m-%d").date()
                except ValueError:
                    return_date = datetime.fromisoformat(return_date).date()
            elif isinstance(return_date, datetime):
                return_date = return_date.date()

            if return_date <= now:
                # Restore to queue - insert right after current index
                restored_member = {
                    "github": entry["github"],
                    "name": entry.get("name", entry["github"]),
                }
                
                if state["queue"]:
                    # Insert right after current index
                    insert_position = (state["current_index"] + 1) % (len(state["queue"]) + 1)
                    state["queue"].insert(insert_position, restored_member)
                    
                    # Adjust current_index if we inserted before or at it
                    if insert_position <= state["current_index"]:
                        state["current_index"] += 1
                else:
                    # Queue is empty, just add them
                    state["queue"].append(restored_member)
                
                restored.append(entry["github"])
            else:
                still_away.append(entry)
        else:
            still_away.append(entry)

    state["pass_until"] = still_away
    return state, restored


# ==============================================================================
# Reviewer Assignment
# ==============================================================================


def get_next_reviewer(state: dict, skip_usernames: set[str] | None = None) -> str | None:
    """
    Get the next reviewer from the queue using round-robin.

    Args:
        state: Current bot state
        skip_usernames: Set of usernames to skip (e.g., issue author)

    Returns the username of the next reviewer, or None if queue is empty.
    """
    if not state["queue"]:
        return None

    skip_usernames = skip_usernames or set()
    queue_size = len(state["queue"])
    start_index = state["current_index"]

    # Try each person in the queue starting from current_index
    for i in range(queue_size):
        index = (start_index + i) % queue_size
        candidate = state["queue"][index]

        if candidate["github"] not in skip_usernames:
            # Found a valid reviewer - advance the index
            state["current_index"] = (index + 1) % queue_size
            return candidate["github"]

    # Everyone in queue is in skip list
    return None


def record_assignment(state: dict, github: str, issue_number: int,
                     issue_type: str) -> None:
    """Record an assignment in the recent_assignments list."""
    assignment = {
        "github": github,
        "issue_number": issue_number,
        "type": issue_type,
        "assigned_at": datetime.now(timezone.utc).isoformat(),
    }

    state["recent_assignments"].insert(0, assignment)
    state["recent_assignments"] = state["recent_assignments"][:MAX_RECENT_ASSIGNMENTS]


# ==============================================================================
# Guidance Text
# ==============================================================================


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

4. When ready, **add the `sign-off: create pr from issue` label** to signal the contributor should create a PR

## Bot Commands

If you need to pass this review:
- `{BOT_MENTION} pass! [reason]` - Pass just this issue to the next reviewer
- `{BOT_MENTION} pass-until! YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} release` - Release your assignment (next in queue will be assigned)

To assign someone else:
- `{BOT_MENTION} assign @username` - Assign a specific reviewer
- `{BOT_MENTION} r? producers` - Request the next reviewer from the queue

Other commands:
- `{BOT_MENTION} claim` - Claim this review for yourself
- `{BOT_MENTION} label +label-name` - Add a label
- `{BOT_MENTION} label -label-name` - Remove a label
- `{BOT_MENTION} queue-status` - Show current queue status
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
- `{BOT_MENTION} pass! [reason]` - Pass just this PR to the next reviewer
- `{BOT_MENTION} pass-until! YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} release` - Release your assignment (next in queue will be assigned)

To assign someone else:
- `{BOT_MENTION} assign @username` - Assign a specific reviewer
- `{BOT_MENTION} r? producers` - Request the next reviewer from the queue

Other commands:
- `{BOT_MENTION} claim` - Claim this review for yourself
- `{BOT_MENTION} label +label-name` - Add a label
- `{BOT_MENTION} label -label-name` - Remove a label
- `{BOT_MENTION} queue-status` - Show current queue status
"""


# ==============================================================================
# Command Parsing & Handling
# ==============================================================================


def parse_command(comment_body: str) -> tuple[str, list[str]] | None:
    """
    Parse a bot command from a comment body.

    Returns (command, args) or None if no command found.
    
    All commands must be prefixed with @guidelines-bot:
    - @guidelines-bot <command> [args]
    - @guidelines-bot r? @username (assign specific user)
    - @guidelines-bot r? producers (assign next from queue)
    """
    # Look for @guidelines-bot <command> pattern
    pattern = rf"{re.escape(BOT_MENTION)}\s+(\S+)(.*)$"
    match = re.search(pattern, comment_body, re.IGNORECASE | re.MULTILINE)

    if not match:
        return None

    command = match.group(1).lower().rstrip("!")
    args_str = match.group(2).strip()

    # Special handling for "@guidelines-bot r? <target>" syntax
    if command == "r?":
        target = args_str.split()[0] if args_str else ""
        if target.lower() == "producers":
            return "assign-from-queue", []
        elif target:
            username = target.lstrip("@")
            return "assign", [f"@{username}"]
        else:
            # No target specified, return as-is to show error
            return "r?", []

    # Parse arguments (handle quoted strings)
    args = []
    if args_str:
        # Simple argument parsing - split on whitespace but respect quotes
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


def handle_pass_command(state: dict, issue_number: int, comment_author: str,
                       reason: str | None) -> tuple[str, bool]:
    """
    Handle the pass! command - skip current reviewer for this issue only.

    Tracks who has passed on each issue to prevent re-assignment.
    Only the first passer gets moved to "next in queue" position.
    Subsequent passers just pass without queue reordering, and the
    original passer remains "next" for future issues.

    Returns (response_message, success).
    """
    # Get or create the tracking entry for this issue
    issue_key = str(issue_number)  # YAML keys are strings
    if "active_reviews" not in state:
        state["active_reviews"] = {}
    if issue_key not in state["active_reviews"]:
        state["active_reviews"][issue_key] = {"skipped": [], "current_reviewer": None}
    
    # Handle old format (just a list) - migrate to new format
    if isinstance(state["active_reviews"][issue_key], list):
        state["active_reviews"][issue_key] = {
            "skipped": state["active_reviews"][issue_key],
            "current_reviewer": None
        }
    
    issue_data = state["active_reviews"][issue_key]
    
    # Determine who the current reviewer is:
    # 1. First check our tracked state
    # 2. Fall back to GitHub assignees
    passed_reviewer = issue_data.get("current_reviewer")
    if not passed_reviewer:
        current_assignees = get_issue_assignees(issue_number)
        passed_reviewer = current_assignees[0] if current_assignees else None
    
    if not passed_reviewer:
        return "❌ No reviewer is currently assigned to pass.", False

    # Check if this is the first pass on this issue
    is_first_pass = len(issue_data["skipped"]) == 0
    
    # Record this reviewer as having passed on this issue
    if passed_reviewer not in issue_data["skipped"]:
        issue_data["skipped"].append(passed_reviewer)

    # Find the passed reviewer's entry and position in the queue (for first pass reordering)
    passed_entry = None
    passed_index = None
    for i, member in enumerate(state["queue"]):
        if member["github"].lower() == passed_reviewer.lower():
            passed_entry = member
            passed_index = i
            break

    # Get the issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")

    # Build skip set: everyone who has passed on this issue + issue author
    skip_set = set(issue_data["skipped"])
    if issue_author:
        skip_set.add(issue_author)

    # Save current index - we'll restore it for non-first passes
    saved_index = state["current_index"]

    # Find next reviewer, skipping all who have passed
    next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not next_reviewer:
        # Restore index since we're failing
        state["current_index"] = saved_index
        return ("❌ No other reviewers available. Everyone in the queue has either "
                "passed on this issue or is the author."), False

    # Only reorder queue on the FIRST pass for this issue
    if is_first_pass and passed_entry is not None:
        # Find the substitute's current position
        substitute_index = None
        for i, member in enumerate(state["queue"]):
            if member["github"].lower() == next_reviewer.lower():
                substitute_index = i
                break

        if substitute_index is not None:
            # Reorder: move passed reviewer to right after substitute
            state["queue"].pop(passed_index)

            # Adjust substitute_index if it was after the removed position
            if substitute_index > passed_index:
                substitute_index -= 1

            # Insert passed reviewer right after substitute
            insert_position = substitute_index + 1
            state["queue"].insert(insert_position, passed_entry)

            # Set index to point at passed reviewer (they're next for future issues)
            state["current_index"] = insert_position
    else:
        # NOT first pass - restore the index so original passer stays "next"
        state["current_index"] = saved_index

    # Unassign the passed reviewer first (best effort - may fail if no permissions)
    unassign_reviewer(issue_number, passed_reviewer)

    # Assign the substitute to this issue (best effort)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, next_reviewer)  # Don't fail if this doesn't work
    
    # Track the new reviewer in our state (this is the source of truth)
    set_current_reviewer(state, issue_number, next_reviewer)

    # Record the assignment
    record_assignment(state, next_reviewer, issue_number, "pr" if is_pr else "issue")

    reason_text = f" Reason: {reason}" if reason else ""
    if is_first_pass:
        return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n"
                f"@{next_reviewer} is now assigned as the reviewer.\n\n"
                f"_@{passed_reviewer} is next in queue for future issues._"), True
    else:
        # Get the original passer (first in the skip list)
        original_passer = issue_data["skipped"][0]
        return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n"
                f"@{next_reviewer} is now assigned as the reviewer.\n\n"
                f"_@{original_passer} remains next in queue for future issues._"), True


def handle_pass_until_command(state: dict, issue_number: int, comment_author: str,
                              return_date: str, reason: str | None) -> tuple[str, bool]:
    """
    Handle the pass-until! command - remove user from queue until date.

    Returns (response_message, success).
    """
    # Validate date format
    try:
        parsed_date = datetime.strptime(return_date, "%Y-%m-%d").date()
    except ValueError:
        return (f"❌ Invalid date format: `{return_date}`. "
                f"Please use YYYY-MM-DD format (e.g., 2025-02-01)."), False

    # Check date is in the future
    if parsed_date <= datetime.now(timezone.utc).date():
        return "❌ Return date must be in the future.", False

    # Find the user in the queue
    user_in_queue = None
    user_index = None
    for i, member in enumerate(state["queue"]):
        if member["github"].lower() == comment_author.lower():
            user_in_queue = member
            user_index = i
            break

    if not user_in_queue:
        # Check if they're already in pass_until
        for entry in state.get("pass_until", []):
            if entry["github"].lower() == comment_author.lower():
                # Update their return date
                entry["return_date"] = return_date
                if reason:
                    entry["reason"] = reason
                return (f"✅ Updated your return date to {return_date}.\n\n"
                        f"You're already marked as away."), True

        return (f"❌ @{comment_author} is not in the reviewer queue. "
                f"Only Producers can use this command."), False

    # Move from queue to pass_until
    state["queue"].remove(user_in_queue)

    pass_entry = {
        "github": user_in_queue["github"],
        "name": user_in_queue.get("name", user_in_queue["github"]),
        "return_date": return_date,
        "original_queue_position": user_index,
    }
    if reason:
        pass_entry["reason"] = reason

    state["pass_until"].append(pass_entry)

    # Adjust current_index if needed
    if state["queue"]:
        if user_index is not None and user_index < state["current_index"]:
            state["current_index"] = max(0, state["current_index"] - 1)
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0

    # Check if this user was assigned to the current issue
    # Check both our tracked state and GitHub assignees
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            tracked_reviewer = issue_data.get("current_reviewer")
    
    current_assignees = get_issue_assignees(issue_number)
    is_current_reviewer = (
        (tracked_reviewer and tracked_reviewer.lower() == comment_author.lower()) or
        comment_author.lower() in [a.lower() for a in current_assignees]
    )
    
    reassigned_msg = ""

    if is_current_reviewer:
        # Need to reassign
        unassign_reviewer(issue_number, comment_author)
        
        issue_author = os.environ.get("ISSUE_AUTHOR", "")
        skip_set = {issue_author} if issue_author else set()
        next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)

        if next_reviewer:
            is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
            assign_reviewer(issue_number, next_reviewer)
            set_current_reviewer(state, issue_number, next_reviewer)
            record_assignment(state, next_reviewer, issue_number,
                            "pr" if is_pr else "issue")
            reassigned_msg = f"\n\n@{next_reviewer} has been assigned as the new reviewer for this issue."
        else:
            # Clear the current reviewer
            if "active_reviews" in state and issue_key in state["active_reviews"]:
                if isinstance(state["active_reviews"][issue_key], dict):
                    state["active_reviews"][issue_key]["current_reviewer"] = None
            reassigned_msg = "\n\n⚠️ No other reviewers available to assign."

    reason_text = f" ({reason})" if reason else ""
    return (f"✅ @{comment_author} is now away until {return_date}{reason_text}.\n\n"
            f"You'll be automatically added back to the queue on that date."
            f"{reassigned_msg}"), True


def handle_label_command(issue_number: int, label_string: str) -> tuple[str, bool]:
    """
    Handle the label command - add or remove labels.
    
    Parses a string like "+chapter: expressions -chapter: values +decidability: decidable"
    and applies each label operation.

    Returns (response_message, success).
    """
    import re
    
    # Find all +label and -label patterns
    # Labels can contain spaces, colons, etc. - they end at the next +/- or end of string
    pattern = r'([+-])([^+-]+)'
    matches = re.findall(pattern, label_string)
    
    if not matches:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False
    
    results = []
    all_success = True
    
    for action, label in matches:
        label = label.strip()
        if not label:
            continue
            
        if action == "+":
            if add_label(issue_number, label):
                results.append(f"✅ Added label `{label}`")
            else:
                results.append(f"❌ Failed to add label `{label}`")
                all_success = False
        elif action == "-":
            if remove_label(issue_number, label):
                results.append(f"✅ Removed label `{label}`")
            else:
                results.append(f"❌ Failed to remove label `{label}`")
                all_success = False
    
    if not results:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False
    
    return "\n".join(results), all_success


def handle_sync_members_command(state: dict) -> tuple[str, bool]:
    """
    Handle the sync-members command - sync queue with members.md.

    Returns (response_message, success).
    """
    state, changes = sync_members_with_queue(state)

    if changes:
        changes_text = "\n".join(f"- {c}" for c in changes)
        return f"✅ Queue synced with members.md:\n\n{changes_text}", True
    else:
        return "✅ Queue is already in sync with members.md.", True


def handle_status_command(state: dict) -> tuple[str, bool]:
    """
    Handle the status command - show current queue status.

    Returns (response_message, success).
    """
    queue_size = len(state["queue"])

    if queue_size == 0:
        return "📊 **Queue Status**: No reviewers in queue.", True

    current_index = state["current_index"]
    next_up = state["queue"][current_index]["github"]

    # Build queue list
    queue_list = []
    for i, member in enumerate(state["queue"]):
        marker = "→" if i == current_index else " "
        queue_list.append(f"{marker} {i + 1}. @{member['github']}")

    queue_text = "\n".join(queue_list)

    # Build pass_until list
    away_text = ""
    if state.get("pass_until"):
        away_list = []
        for entry in state["pass_until"]:
            reason = f" ({entry['reason']})" if entry.get("reason") else ""
            away_list.append(
                f"- @{entry['github']} until {entry['return_date']}{reason}"
            )
        away_text = "\n\n**Currently Away:**\n" + "\n".join(away_list)

    return (f"📊 **Queue Status**\n\n"
            f"**Next up:** @{next_up}\n\n"
            f"**Queue ({queue_size} reviewers):**\n```\n{queue_text}\n```"
            f"{away_text}"), True


def handle_claim_command(state: dict, issue_number: int,
                        comment_author: str) -> tuple[str, bool]:
    """
    Handle the claim command - assign yourself as reviewer.

    Returns (response_message, success).
    """
    # Check if user is in the queue (is a Producer)
    is_producer = any(
        m["github"].lower() == comment_author.lower()
        for m in state["queue"]
    )
    is_away = any(
        m["github"].lower() == comment_author.lower()
        for m in state.get("pass_until", [])
    )

    if not is_producer and not is_away:
        return (f"❌ @{comment_author} is not in the reviewer queue. "
                f"Only Producers can claim reviews."), False

    if is_away:
        return (f"❌ @{comment_author} is currently marked as away. "
                f"Please use `{BOT_MENTION} pass-until!` to update your return date first, "
                f"or wait until your scheduled return."), False

    # Get current assignees
    current_assignees = get_issue_assignees(issue_number)

    # Remove existing assignees
    for assignee in current_assignees:
        unassign_reviewer(issue_number, assignee)

    # Assign the claimer (best effort)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, comment_author)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, comment_author)

    # Record the assignment
    record_assignment(state, comment_author, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    return f"✅ @{comment_author} has claimed this review{prev_text}.", True


def handle_release_command(state: dict, issue_number: int,
                          comment_author: str) -> tuple[str, bool]:
    """
    Handle the release command - release your assignment.

    Returns (response_message, success).
    """
    # Check who the current reviewer is (from our state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            tracked_reviewer = issue_data.get("current_reviewer")
    
    # Also check GitHub assignees
    current_assignees = get_issue_assignees(issue_number)

    # Determine if the comment author is the current reviewer
    is_tracked = tracked_reviewer and tracked_reviewer.lower() == comment_author.lower()
    is_assigned = comment_author.lower() in [a.lower() for a in current_assignees]

    if not is_tracked and not is_assigned:
        if tracked_reviewer:
            return (f"❌ @{comment_author} is not the current reviewer. "
                    f"Current reviewer: @{tracked_reviewer}"), False
        elif current_assignees:
            return (f"❌ @{comment_author} is not assigned to this issue/PR. "
                    f"Current assignee(s): @{', @'.join(current_assignees)}"), False
        else:
            return "❌ No reviewer is currently assigned to release.", False

    # Remove the assignment (best effort)
    unassign_reviewer(issue_number, comment_author)

    # Get the issue author to skip them when assigning next reviewer
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author, comment_author} if issue_author else {comment_author}

    # Assign the next person in the queue
    next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if next_reviewer:
        is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
        assign_reviewer(issue_number, next_reviewer)
        set_current_reviewer(state, issue_number, next_reviewer)
        record_assignment(state, next_reviewer, issue_number,
                        "pr" if is_pr else "issue")
        return (f"✅ @{comment_author} has released this review.\n\n"
                f"@{next_reviewer} is now assigned as the reviewer."), True
    else:
        # Clear the current reviewer since no one is assigned
        if "active_reviews" in state and issue_key in state["active_reviews"]:
            if isinstance(state["active_reviews"][issue_key], dict):
                state["active_reviews"][issue_key]["current_reviewer"] = None
        return (f"✅ @{comment_author} has released this review.\n\n"
                f"⚠️ No other reviewers available in the queue."), True


def handle_assign_command(state: dict, issue_number: int,
                         username: str) -> tuple[str, bool]:
    """
    Handle the assign command - assign a specific person as reviewer.

    Also handles r? @username syntax.

    Returns (response_message, success).
    """
    # Clean up username (remove @ if present)
    username = username.lstrip("@")

    if not username:
        return (f"❌ Missing username. Usage: `{BOT_MENTION} assign @username` "
                f"or `r? @username`"), False

    # Check if user is in the queue (is a Producer)
    is_producer = any(
        m["github"].lower() == username.lower()
        for m in state["queue"]
    )
    is_away = any(
        m["github"].lower() == username.lower()
        for m in state.get("pass_until", [])
    )

    if not is_producer and not is_away:
        return (f"⚠️ @{username} is not in the reviewer queue (not a Producer). "
                f"Assigning anyway, but they may not have review permissions."), False

    if is_away:
        # Find their return date
        for entry in state.get("pass_until", []):
            if entry["github"].lower() == username.lower():
                return_date = entry.get("return_date", "unknown")
                return (f"⚠️ @{username} is currently marked as away until {return_date}. "
                        f"Consider assigning someone else or waiting."), False

    # Get current assignees and remove them
    current_assignees = get_issue_assignees(issue_number)
    for assignee in current_assignees:
        unassign_reviewer(issue_number, assignee)

    # Assign the specified user (best effort)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, username)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, username)

    # Record the assignment (but don't advance queue - this is manual assignment)
    record_assignment(state, username, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    return f"✅ @{username} has been assigned as reviewer{prev_text}.", True


def handle_assign_from_queue_command(state: dict, issue_number: int) -> tuple[str, bool]:
    """
    Handle the assign-from-queue command (r? producers) - assign next from queue.

    This advances the round-robin queue, unlike manual assignment.

    Returns (response_message, success).
    """
    # Get current assignees and remove them
    current_assignees = get_issue_assignees(issue_number)
    for assignee in current_assignees:
        unassign_reviewer(issue_number, assignee)

    # Get the issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer from the queue (this advances the queue)
    next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not next_reviewer:
        return ("❌ No reviewers available in the queue. "
                f"Please use `{BOT_MENTION} sync-members` to update the queue."), False

    # Assign the reviewer (best effort - may fail if no permissions)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, next_reviewer)

    # Track the reviewer in our state (source of truth for pass command)
    set_current_reviewer(state, issue_number, next_reviewer)

    # Record the assignment
    record_assignment(state, next_reviewer, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    # Post the appropriate guidance
    if is_pr:
        guidance = get_pr_guidance(next_reviewer, issue_author)
    else:
        guidance = get_issue_guidance(next_reviewer, issue_author)

    post_comment(issue_number, guidance)

    return f"✅ @{next_reviewer} (next in queue) has been assigned as reviewer{prev_text}.", True


# ==============================================================================
# Event Handlers
# ==============================================================================


def set_current_reviewer(state: dict, issue_number: int, reviewer: str) -> None:
    """Track the designated reviewer for an issue/PR in our state."""
    issue_key = str(issue_number)
    if "active_reviews" not in state:
        state["active_reviews"] = {}
    if issue_key not in state["active_reviews"]:
        state["active_reviews"][issue_key] = {"skipped": [], "current_reviewer": None}
    elif isinstance(state["active_reviews"][issue_key], list):
        # Migrate old format
        state["active_reviews"][issue_key] = {
            "skipped": state["active_reviews"][issue_key],
            "current_reviewer": None
        }
    state["active_reviews"][issue_key]["current_reviewer"] = reviewer


def handle_issue_or_pr_opened(state: dict) -> bool:
    """
    Handle when an issue or PR is opened with the coding guideline label.

    Returns True if we took action, False otherwise.
    """
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    print(f"Processing opened event for #{issue_number}")

    # Check if already has a reviewer (check our tracked state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    
    current_assignees = get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers/assignees: {current_assignees}")
        return False

    # Check for coding guideline label
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    print(f"ISSUE_LABELS env: {labels_json}")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        print("Failed to parse ISSUE_LABELS as JSON")
        labels = []

    if CODING_GUIDELINE_LABEL not in labels:
        print(f"Issue #{issue_number} does not have '{CODING_GUIDELINE_LABEL}' label (labels: {labels})")
        return False

    # Get issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer
    reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not reviewer:
        post_comment(issue_number,
                    f"⚠️ No reviewers available in the queue. "
                    f"Please use `{BOT_MENTION} sync-members` to update the queue.")
        return False

    # Assign the reviewer (best effort - may fail if no permissions)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, reviewer)
    
    # Track the reviewer in our state (source of truth for pass command)
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    # Post guidance comment
    if is_pr:
        guidance = get_pr_guidance(reviewer, issue_author)
    else:
        guidance = get_issue_guidance(reviewer, issue_author)

    post_comment(issue_number, guidance)

    return True


def handle_labeled_event(state: dict) -> bool:
    """
    Handle when an issue or PR is labeled with the coding guideline label.

    We already know from LABEL_NAME that the correct label was added,
    so we skip the label check that handle_issue_or_pr_opened does.
    """
    label_name = os.environ.get("LABEL_NAME", "")

    if label_name != CODING_GUIDELINE_LABEL:
        print(f"Label '{label_name}' is not '{CODING_GUIDELINE_LABEL}', skipping")
        return False

    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    # Check if already has a reviewer (check our tracked state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    
    if tracked_reviewer:
        print(f"Issue #{issue_number} already has tracked reviewer: {tracked_reviewer}")
        return False
    
    current_assignees = get_issue_assignees(issue_number)
    if current_assignees:
        print(f"Issue #{issue_number} already has reviewers: {current_assignees}")
        return False

    print(f"Processing labeled event for #{issue_number}, author: {os.environ.get('ISSUE_AUTHOR', '')}")

    # Get issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer
    reviewer = get_next_reviewer(state, skip_usernames=skip_set)
    print(f"Selected reviewer for #{issue_number}: {reviewer}")

    if not reviewer:
        post_comment(issue_number,
                    f"⚠️ No reviewers available in the queue. "
                    f"Please use `{BOT_MENTION} sync-members` to update the queue.")
        return False

    # Assign the reviewer (best effort - may fail if no permissions)
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assign_reviewer(issue_number, reviewer)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    # Post guidance comment
    if is_pr:
        guidance = get_pr_guidance(reviewer, issue_author)
    else:
        guidance = get_issue_guidance(reviewer, issue_author)

    post_comment(issue_number, guidance)

    return True


def handle_closed_event(state: dict) -> bool:
    """
    Handle when an issue or PR is closed.
    
    Cleans up the active_reviews entry to prevent state from growing indefinitely.
    
    Returns True if we modified state, False otherwise.
    """
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found for closed event")
        return False

    issue_key = str(issue_number)
    
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        print(f"Cleaned up active_reviews entry for #{issue_number}")
        return True
    
    print(f"No active_reviews entry found for #{issue_number}")
    return False


def handle_comment_event(state: dict) -> bool:
    """
    Handle a comment event - check for bot commands.

    Returns True if we took action, False otherwise.
    """
    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_id = os.environ.get("COMMENT_ID", "")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))

    if not comment_body or not issue_number:
        return False

    # Parse for bot command
    parsed = parse_command(comment_body)
    if not parsed:
        return False

    command, args = parsed
    print(f"Parsed command: {command}, args: {args}")

    response = ""
    success = False
    state_changed = False

    # Handle each command
    if command == "pass":
        reason = " ".join(args) if args else None
        response, success = handle_pass_command(state, issue_number, comment_author, reason)
        state_changed = success

    elif command == "pass-until":
        if not args:
            response = (f"❌ Missing date. Usage: `{BOT_MENTION} pass-until! YYYY-MM-DD [reason]`")
            success = False
        else:
            return_date = args[0]
            reason = " ".join(args[1:]) if len(args) > 1 else None
            response, success = handle_pass_until_command(
                state, issue_number, comment_author, return_date, reason
            )
            state_changed = success

    elif command == "label":
        if not args:
            response = (f"❌ Missing label. Usage: `{BOT_MENTION} label +label-name` or "
                       f"`{BOT_MENTION} label -label-name`")
            success = False
        else:
            # Rejoin all args to handle labels with spaces
            # Then parse for +label and -label patterns
            full_arg = " ".join(args)
            response, success = handle_label_command(issue_number, full_arg)

    elif command == "sync-members":
        response, success = handle_sync_members_command(state)
        state_changed = success

    elif command == "queue-status":
        response, success = handle_status_command(state)

    elif command == "claim":
        response, success = handle_claim_command(state, issue_number, comment_author)
        state_changed = success

    elif command == "release":
        response, success = handle_release_command(state, issue_number, comment_author)
        state_changed = success

    elif command == "assign":
        if not args:
            response = (f"❌ Missing username. Usage: `{BOT_MENTION} assign @username` "
                       f"or `r? @username`")
            success = False
        else:
            username = args[0]
            response, success = handle_assign_command(state, issue_number, username)
            state_changed = success

    elif command == "assign-from-queue":
        # Handle "r? producers" - assign next from round-robin queue
        response, success = handle_assign_from_queue_command(state, issue_number)
        state_changed = success

    elif command == "r?":
        # Handle "r?" with no target - show usage error
        response = (f"❌ Missing target. Usage:\n"
                   f"- `{BOT_MENTION} r? @username` - Assign a specific reviewer\n"
                   f"- `{BOT_MENTION} r? producers` - Assign next reviewer from queue")
        success = False

    else:
        response = (f"❌ Unknown command: `{command}`\n\n"
                   f"Available commands:\n"
                   f"- `{BOT_MENTION} pass! [reason]` - Pass this review to next in queue\n"
                   f"- `{BOT_MENTION} pass-until! YYYY-MM-DD [reason]` - Step away from queue\n"
                   f"- `{BOT_MENTION} claim` - Claim this review for yourself\n"
                   f"- `{BOT_MENTION} release` - Release your assignment\n"
                   f"- `{BOT_MENTION} assign @username` - Assign specific reviewer\n"
                   f"- `{BOT_MENTION} r? producers` - Assign next reviewer from queue\n"
                   f"- `{BOT_MENTION} label +/-label-name` - Add/remove labels\n"
                   f"- `{BOT_MENTION} sync-members` - Sync queue with members.md\n"
                   f"- `{BOT_MENTION} queue-status` - Show queue status")
        success = False

    # React to the command comment
    if comment_id:
        add_reaction(int(comment_id), "eyes")
        if success:
            add_reaction(int(comment_id), "+1")

    # Post response
    if response:
        post_comment(issue_number, response)

    return state_changed


def handle_manual_dispatch(state: dict) -> bool:
    """Handle manual workflow dispatch."""
    action = os.environ.get("MANUAL_ACTION", "")

    if action == "sync-members":
        state, changes = sync_members_with_queue(state)
        if changes:
            print(f"Sync changes: {changes}")
        return True

    elif action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False

    return False


# ==============================================================================
# Main
# ==============================================================================


def main():
    """Main entry point for the reviewer bot."""
    event_name = os.environ.get("EVENT_NAME", "")
    event_action = os.environ.get("EVENT_ACTION", "")

    print(f"Event: {event_name}, Action: {event_action}")

    # Load current state
    state = load_state()

    # Process any expired pass-until entries
    state, restored = process_pass_until_expirations(state)
    if restored:
        print(f"Restored from pass-until: {restored}")

    # Always sync members on any event
    state, sync_changes = sync_members_with_queue(state)
    if sync_changes:
        print(f"Members sync changes: {sync_changes}")

    # Handle the event
    state_changed = False

    if event_name == "issues":
        if event_action == "opened":
            state_changed = handle_issue_or_pr_opened(state)
        elif event_action == "labeled":
            state_changed = handle_labeled_event(state)
        elif event_action == "closed":
            state_changed = handle_closed_event(state)

    elif event_name == "pull_request_target":
        if event_action == "opened":
            state_changed = handle_issue_or_pr_opened(state)
        elif event_action == "labeled":
            state_changed = handle_labeled_event(state)
        elif event_action == "closed":
            state_changed = handle_closed_event(state)

    elif event_name == "issue_comment":
        if event_action == "created":
            state_changed = handle_comment_event(state)

    elif event_name == "workflow_dispatch":
        state_changed = handle_manual_dispatch(state)

    # Save state if changed (or if we synced members/pass-until)
    if state_changed or sync_changes or restored:
        save_state(state)
        # Set output for the workflow
        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
            f.write("state_changed=true\n")
    else:
        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
            f.write("state_changed=false\n")


if __name__ == "__main__":
    main()
