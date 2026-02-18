#!/usr/bin/env python3
"""
Reviewer Bot for Safety-Critical Rust Coding Guidelines

This bot manages round-robin assignment of reviewers for coding guideline and
FLS audit issues and PRs. It supports commands for passing reviews, vacations,
and label management.

All commands must be prefixed with @guidelines-bot /<command>:

  @guidelines-bot /pass [reason]
    - Skip the assigned reviewer for this issue/PR and assign the next person
    - The skipped reviewer stays in queue position for future assignments

  @guidelines-bot /away YYYY-MM-DD [reason]
    - Remove yourself from the queue until the specified date
    - Automatically assigns the next available reviewer

  @guidelines-bot /claim
    - Assign yourself as the reviewer for this issue/PR
    - Removes any existing reviewer assignment

  @guidelines-bot /release [reason]
    - Release your own assignment from this issue/PR
    - Leaves this issue/PR unassigned

  @guidelines-bot /release @username [reason]
    - Release someone else's assignment from this issue/PR (triage+ required)
    - Does NOT auto-assign the next reviewer (use /pass for that)

  @guidelines-bot /rectify
    - Reconcile this issue/PR's review state from GitHub review history
    - Useful when cross-repo review events cannot persist state immediately

  @guidelines-bot /r? @username
    - Assign a specific reviewer

  @guidelines-bot /r? producers
    - Assign the next reviewer from the round-robin queue
    - Useful for requesting a reviewer on an already-open issue/PR

  @guidelines-bot /label +label-name
    - Add a label to the issue/PR

  @guidelines-bot /label -label-name
    - Remove a label from the issue/PR

  @guidelines-bot /accept-no-fls-changes
    - Update spec.lock and open a PR when the audit reports no guideline impact

  @guidelines-bot /sync-members
    - Manually trigger sync of the queue with members.md

  @guidelines-bot /queue
    - Show current queue status and who's next up

  @guidelines-bot /commands
    - Show all available commands
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# GitHub API interaction
import requests
import yaml

# ==============================================================================
# Configuration
# ==============================================================================

BOT_NAME = "guidelines-bot"
BOT_MENTION = f"@{BOT_NAME}"
CODING_GUIDELINE_LABEL = "coding guideline"
FLS_AUDIT_LABEL = "fls-audit"
REVIEW_LABELS = {CODING_GUIDELINE_LABEL, FLS_AUDIT_LABEL}
# State is stored in a dedicated GitHub issue body (set via environment variable)
STATE_ISSUE_NUMBER = int(os.environ.get("STATE_ISSUE_NUMBER", "0"))
# Members file is in the consortium repo, not this repo
MEMBERS_URL = "https://raw.githubusercontent.com/rustfoundation/safety-critical-rust-consortium/main/subcommittee/coding-guidelines/members.md"
MAX_RECENT_ASSIGNMENTS = 20

STATE_BLOCK_START_MARKER = "<!-- REVIEWER_BOT_STATE_START -->"
STATE_BLOCK_END_MARKER = "<!-- REVIEWER_BOT_STATE_END -->"
LOCK_BLOCK_START_MARKER = "<!-- REVIEWER_BOT_LOCK_START -->"
LOCK_BLOCK_END_MARKER = "<!-- REVIEWER_BOT_LOCK_END -->"

LOCK_SCHEMA_VERSION = 1
LOCK_LEASE_TTL_SECONDS = int(os.environ.get("REVIEWER_BOT_LOCK_TTL_SECONDS", "300"))
LOCK_RETRY_BASE_SECONDS = float(os.environ.get("REVIEWER_BOT_LOCK_RETRY_SECONDS", "2"))
LOCK_MAX_WAIT_SECONDS = int(os.environ.get("REVIEWER_BOT_LOCK_MAX_WAIT_SECONDS", "1200"))
LOCK_API_RETRY_LIMIT = int(os.environ.get("REVIEWER_BOT_LOCK_API_RETRY_LIMIT", "5"))
LOCK_RENEWAL_WINDOW_SECONDS = int(
    os.environ.get("REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS", "60")
)
LOCK_REF_NAME = os.environ.get("REVIEWER_BOT_LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
LOCK_REF_BOOTSTRAP_BRANCH = os.environ.get("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", "main")
LOCK_COMMIT_MARKER = "reviewer-bot-lock-v1"

EVENT_INTENT_MUTATING = "mutating"
EVENT_INTENT_NON_MUTATING_DEFER = "non_mutating_defer"
EVENT_INTENT_NON_MUTATING_READONLY = "non_mutating_readonly"

MANDATORY_TRIAGE_APPROVER_LABEL = "triage approver required"
MANDATORY_TRIAGE_PING_TARGETS = [
    "@PLeVasseur",
    "@felix91gr",
    "@rcseacord",
    "@plaindocs",
    "@AlexCeleste",
    "@sei-dsvoboda",
]

REVIEWER_REQUEST_422_TEMPLATE = (
    "@{reviewer} is designated as reviewer by queue rotation, but GitHub could not add them to PR "
    "Reviewers automatically (API 422). A triage+ approver may still be required before merge queue."
)
MANDATORY_TRIAGE_ESCALATION_TEMPLATE = (
    "Mandatory triage approval required before merge queue. Pinging "
    f"{' '.join(MANDATORY_TRIAGE_PING_TARGETS)}. "
    "Label applied: `triage approver required`."
)
MANDATORY_TRIAGE_SATISFIED_TEMPLATE = (
    "Mandatory triage approval satisfied by @{approver}; removed `triage approver required`."
)

LOCK_METADATA_KEYS = [
    "schema_version",
    "lock_state",
    "lock_owner_run_id",
    "lock_owner_workflow",
    "lock_owner_job",
    "lock_token",
    "lock_acquired_at",
    "lock_expires_at",
]

# Review deadline configuration
REVIEW_DEADLINE_DAYS = 14  # Days before first warning
TRANSITION_PERIOD_DAYS = 14  # Days after warning before transition to Observer

# Command definitions - single source of truth for command names and descriptions
# Format: "command": "description"
COMMANDS = {
    "pass": "Pass this review to next in queue",
    "away": "Step away from queue until date (YYYY-MM-DD)",
    "release": "Release your assignment (/release) or another's (/release @username, triage+)",
    "rectify": "Reconcile this issue/PR's review state from GitHub",
    "claim": "Claim this review for yourself",
    "r?": "Assign a reviewer (@username or 'producers')",
    "label": "Add/remove labels (+label-name or -label-name)",
    "accept-no-fls-changes": "Update spec.lock and open PR for a clean audit",
    "sync-members": "Sync queue with members.md",
    "queue": "Show reviewer queue and who's next",
    "commands": "Show all available commands",
}


def get_commands_help() -> str:
    """Generate help text from COMMANDS dict."""
    lines = []
    for cmd, desc in COMMANDS.items():
        lines.append(f"- `{BOT_MENTION} /{cmd}` - {desc}")
    return "\n".join(lines)


# ==============================================================================
# GitHub API Helpers
# ==============================================================================


@dataclass
class GitHubApiResult:
    status_code: int
    payload: Any
    headers: dict[str, str]
    text: str
    ok: bool


@dataclass
class AssignmentAttempt:
    success: bool
    status_code: int | None
    exhausted_retryable_failure: bool = False


@dataclass
class StateIssueSnapshot:
    body: str
    etag: str | None
    html_url: str


@dataclass
class StateIssueBodyParts:
    prefix: str
    state_block_inner: str | None
    between_state_and_lock: str
    lock_block_inner: str | None
    suffix: str
    has_state_markers: bool
    has_lock_markers: bool


@dataclass
class LeaseContext:
    lock_token: str
    lock_owner_run_id: str
    lock_owner_workflow: str
    lock_owner_job: str
    state_issue_url: str
    lock_ref: str = ""
    lock_expires_at: str | None = None


ACTIVE_LEASE_CONTEXT: LeaseContext | None = None


def get_github_token() -> str:
    """Get the GitHub token from environment."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return token


def github_api_request(
    method: str,
    endpoint: str,
    data: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    *,
    suppress_error_log: bool = False,
) -> GitHubApiResult:
    """Make a GitHub API request and return status, payload, and headers."""
    token = get_github_token()
    repo = f"{os.environ['REPO_OWNER']}/{os.environ['REPO_NAME']}"
    url = f"https://api.github.com/repos/{repo}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if extra_headers:
        headers.update(extra_headers)

    response = requests.request(method, url, headers=headers, json=data)

    payload: Any = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = None

    ok = response.status_code < 400
    if not ok and not suppress_error_log:
        print(
            f"GitHub API error: {response.status_code} - {response.text}",
            file=sys.stderr,
        )

    normalized_headers = {key.lower(): value for key, value in response.headers.items()}
    return GitHubApiResult(
        status_code=response.status_code,
        payload=payload,
        headers=normalized_headers,
        text=response.text,
        ok=ok,
    )


def github_api(method: str, endpoint: str, data: dict | None = None) -> Any | None:
    """Backward-compatible wrapper around github_api_request."""
    response = github_api_request(method, endpoint, data)
    if not response.ok:
        return None
    if response.payload is None:
        return {}
    return response.payload


def post_comment(issue_number: int, body: str) -> bool:
    """Post a comment on an issue or PR."""
    result = github_api("POST", f"issues/{issue_number}/comments", {"body": body})
    return result is not None


def get_repo_labels() -> set[str]:
    """Get all labels that exist in the repository."""
    result = github_api("GET", "labels?per_page=100")
    if result and isinstance(result, list):
        return {label["name"] for label in result}
    return set()


def add_label(issue_number: int, label: str) -> bool:
    """Add a label to an issue or PR."""
    result = github_api("POST", f"issues/{issue_number}/labels", {"labels": [label]})
    return result is not None


def remove_label(issue_number: int, label: str) -> bool:
    """Remove a label from an issue or PR."""
    github_api("DELETE", f"issues/{issue_number}/labels/{label}")
    # 404 is ok - label might not exist
    return True


def add_label_with_status(issue_number: int, label: str) -> bool:
    """Add a label with explicit HTTP status handling."""
    response = github_api_request(
        "POST",
        f"issues/{issue_number}/labels",
        {"labels": [label]},
        suppress_error_log=True,
    )
    if response.status_code in {200, 201}:
        return True
    if response.status_code in {401, 403}:
        raise RuntimeError(
            f"Permission denied adding label '{label}' to #{issue_number}: {response.text}"
        )
    print(
        f"WARNING: Failed to add label '{label}' to #{issue_number} "
        f"(status {response.status_code}): {response.text}",
        file=sys.stderr,
    )
    return False


def remove_label_with_status(issue_number: int, label: str) -> bool:
    """Remove a label with explicit HTTP status handling."""
    response = github_api_request(
        "DELETE",
        f"issues/{issue_number}/labels/{label}",
        suppress_error_log=True,
    )
    if response.status_code in {200, 204, 404}:
        return True
    if response.status_code in {401, 403}:
        raise RuntimeError(
            f"Permission denied removing label '{label}' from #{issue_number}: {response.text}"
        )
    print(
        f"WARNING: Failed to remove label '{label}' from #{issue_number} "
        f"(status {response.status_code}): {response.text}",
        file=sys.stderr,
    )
    return False


def ensure_label_exists(label: str) -> bool:
    """Create label if missing; treat 422 as already exists."""
    response = github_api_request(
        "POST",
        "labels",
        {
            "name": label,
            "color": "d73a4a",
            "description": "Indicates triage+ approval is required before merge queue",
        },
        suppress_error_log=True,
    )

    if response.status_code == 201:
        return True
    if response.status_code == 422:
        return True

    print(
        f"WARNING: Failed to ensure label '{label}' exists (status {response.status_code}): "
        f"{response.text}",
        file=sys.stderr,
    )
    return False


def request_reviewer_assignment(issue_number: int, username: str) -> AssignmentAttempt:
    """Request reviewer/assignee with status-aware handling and retries."""
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"

    if is_pr:
        endpoint = f"pulls/{issue_number}/requested_reviewers"
        payload = {"reviewers": [username]}
        assignment_target = "PR reviewer"
    else:
        endpoint = f"issues/{issue_number}/assignees"
        payload = {"assignees": [username]}
        assignment_target = "issue assignee"

    for attempt in range(1, LOCK_API_RETRY_LIMIT + 1):
        response = github_api_request("POST", endpoint, payload, suppress_error_log=True)

        if response.status_code in {200, 201}:
            return AssignmentAttempt(success=True, status_code=response.status_code)

        if response.status_code == 422:
            # Queue policy remains permissive: reviewer is still designated in bot state.
            return AssignmentAttempt(success=False, status_code=422)

        if response.status_code in {401, 403}:
            raise RuntimeError(
                f"Permission denied requesting {assignment_target} @{username} on "
                f"#{issue_number} (status {response.status_code}): {response.text}"
            )

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < LOCK_API_RETRY_LIMIT:
                delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                print(
                    f"Retryable {assignment_target} API failure for @{username} on #{issue_number} "
                    f"(status {response.status_code}); retrying ({attempt}/{LOCK_API_RETRY_LIMIT})"
                )
                time.sleep(delay)
                continue
            return AssignmentAttempt(
                success=False,
                status_code=response.status_code,
                exhausted_retryable_failure=True,
            )

        print(
            f"WARNING: Unexpected {assignment_target} API status {response.status_code} "
            f"for @{username} on #{issue_number}: {response.text}",
            file=sys.stderr,
        )
        return AssignmentAttempt(success=False, status_code=response.status_code)

    return AssignmentAttempt(success=False, status_code=None, exhausted_retryable_failure=True)


def assign_reviewer(issue_number: int, username: str) -> bool:
    """Backward-compatible reviewer assignment boolean wrapper."""
    attempt = request_reviewer_assignment(issue_number, username)
    return attempt.success


def get_assignment_failure_comment(reviewer: str, attempt: AssignmentAttempt) -> str | None:
    """Return truthful assignment warning comment text when GitHub assignment fails."""
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"

    if attempt.status_code == 422:
        if is_pr:
            return REVIEWER_REQUEST_422_TEMPLATE.format(reviewer=reviewer)
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not "
            "add them as an assignee automatically (API 422)."
        )

    if attempt.exhausted_retryable_failure:
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not "
            f"add them to PR Reviewers automatically after retries (status {attempt.status_code}). "
            "A triage+ approver may still be required before merge queue."
        )

    return None


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


def check_user_permission(username: str, required_permission: str = "triage") -> bool:
    """
    Check if a user has at least the required permission level on the repo.
    
    Permission levels (lowest to highest): read, triage, write, maintain, admin
    The permissions object has boolean flags for each level, and higher levels
    include all lower permissions (e.g., admin has triage=True).
    
    Args:
        username: GitHub username to check
        required_permission: Permission level required ("triage", "push", "maintain", "admin")
    
    Returns:
        True if user has the required permission, False otherwise.
    """
    result = github_api("GET", f"collaborators/{username}/permission")
    if not result:
        return False
    
    # The API returns a permissions object with boolean flags
    permissions = result.get("user", {}).get("permissions", {})
    return permissions.get(required_permission, False)


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


def default_state_issue_prefix() -> str:
    """Return canonical prefix text for state issue layout."""
    return (
        "## Reviewer Bot State\n\n"
        "> WARNING: DO NOT EDIT MANUALLY - This issue is automatically maintained by the reviewer bot.\n"
        "> Use bot commands instead (see "
        "[CONTRIBUTING.md](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/blob/main/CONTRIBUTING.md) "
        "for details).\n\n"
        "This issue tracks the round-robin assignment of reviewers for coding guidelines.\n\n"
        "### Current State\n\n"
    )


def split_state_issue_body(body: str) -> StateIssueBodyParts:
    """Split state issue body into prefix, state block, lock block, and suffix."""
    if not body:
        return StateIssueBodyParts(
            prefix=default_state_issue_prefix(),
            state_block_inner=None,
            between_state_and_lock="\n\n",
            lock_block_inner=None,
            suffix="\n",
            has_state_markers=False,
            has_lock_markers=False,
        )

    state_start = body.find(STATE_BLOCK_START_MARKER)
    state_end = body.find(STATE_BLOCK_END_MARKER)
    lock_start = body.find(LOCK_BLOCK_START_MARKER)
    lock_end = body.find(LOCK_BLOCK_END_MARKER)

    has_state_markers = state_start >= 0 and state_end > state_start
    has_lock_markers = lock_start >= 0 and lock_end > lock_start

    if has_state_markers and has_lock_markers and state_end < lock_start:
        return StateIssueBodyParts(
            prefix=body[:state_start],
            state_block_inner=body[state_start + len(STATE_BLOCK_START_MARKER):state_end],
            between_state_and_lock=body[state_end + len(STATE_BLOCK_END_MARKER):lock_start],
            lock_block_inner=body[lock_start + len(LOCK_BLOCK_START_MARKER):lock_end],
            suffix=body[lock_end + len(LOCK_BLOCK_END_MARKER):],
            has_state_markers=True,
            has_lock_markers=True,
        )

    # Partial/legacy format fallback: migrate to canonical marker layout.
    return StateIssueBodyParts(
        prefix=default_state_issue_prefix(),
        state_block_inner=None,
        between_state_and_lock="\n\n",
        lock_block_inner=None,
        suffix="\n",
        has_state_markers=False,
        has_lock_markers=False,
    )


def extract_fenced_block(inner_block: str, language_pattern: str) -> str | None:
    """Extract fenced block content from marker inner block."""
    if not inner_block:
        return None

    match = re.search(
        rf"```(?:{language_pattern})\n(.*?)\n```",
        inner_block,
        re.DOTALL,
    )
    if match:
        return match.group(1)
    return None


def normalize_lock_metadata(lock_meta: dict | None) -> dict:
    """Normalize lock metadata to schema v1 keys."""
    normalized: dict[str, Any] = dict.fromkeys(LOCK_METADATA_KEYS)
    normalized["schema_version"] = LOCK_SCHEMA_VERSION

    if not isinstance(lock_meta, dict):
        return normalized

    for key in LOCK_METADATA_KEYS:
        if key == "schema_version":
            schema_value = lock_meta.get("schema_version")
            if isinstance(schema_value, int):
                normalized["schema_version"] = schema_value
            continue
        if key in lock_meta:
            normalized[key] = lock_meta.get(key)

    return normalized


def parse_state_yaml_from_issue_body(body: str) -> dict:
    """Parse YAML state from issue body markers or legacy YAML block."""
    parts = split_state_issue_body(body)

    yaml_content = None
    if parts.has_state_markers and parts.state_block_inner is not None:
        yaml_content = extract_fenced_block(parts.state_block_inner, "ya?ml")

    if yaml_content is None:
        yaml_match = re.search(r"```ya?ml\n(.*?)\n```", body, re.DOTALL)
        if yaml_match:
            yaml_content = yaml_match.group(1)
        else:
            yaml_content = body

    try:
        state = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as exc:
        print(f"WARNING: Failed to parse state YAML: {exc}", file=sys.stderr)
        state = {}

    if not isinstance(state, dict):
        return {}
    return state


def parse_lock_metadata_from_issue_body(body: str) -> dict:
    """Parse lock metadata JSON block from issue body markers."""
    parts = split_state_issue_body(body)
    if not parts.has_lock_markers or parts.lock_block_inner is None:
        return normalize_lock_metadata(None)

    lock_json = extract_fenced_block(parts.lock_block_inner, "json")
    if lock_json is None:
        return normalize_lock_metadata(None)

    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError as exc:
        print(f"WARNING: Failed to parse lock metadata JSON: {exc}", file=sys.stderr)
        return normalize_lock_metadata(None)

    if not isinstance(parsed, dict):
        return normalize_lock_metadata(None)

    return normalize_lock_metadata(parsed)


def render_marked_fenced_block(
    start_marker: str,
    end_marker: str,
    language: str,
    content: str,
) -> str:
    """Render a marker-delimited fenced block."""
    normalized = content.rstrip("\n")
    return f"{start_marker}\n```{language}\n{normalized}\n```\n{end_marker}"


def render_state_issue_body(
    state: dict,
    lock_meta: dict,
    base_body: str | None = None,
    *,
    preserve_state_block: bool = False,
) -> str:
    """Render full issue body preserving markers and surrounding text."""
    parts = split_state_issue_body(base_body or "")

    if preserve_state_block and parts.has_state_markers and parts.state_block_inner is not None:
        state_section = f"{STATE_BLOCK_START_MARKER}{parts.state_block_inner}{STATE_BLOCK_END_MARKER}"
    else:
        yaml_content = yaml.dump(
            state,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        state_section = render_marked_fenced_block(
            STATE_BLOCK_START_MARKER,
            STATE_BLOCK_END_MARKER,
            "yaml",
            yaml_content,
        )

    lock_json = json.dumps(normalize_lock_metadata(lock_meta), indent=2, sort_keys=False)
    lock_section = render_marked_fenced_block(
        LOCK_BLOCK_START_MARKER,
        LOCK_BLOCK_END_MARKER,
        "json",
        lock_json,
    )

    prefix = parts.prefix or default_state_issue_prefix()
    between = parts.between_state_and_lock if parts.has_state_markers and parts.has_lock_markers else "\n\n"
    suffix = parts.suffix if parts.has_lock_markers else "\n"

    return f"{prefix}{state_section}{between}{lock_section}{suffix}"


def parse_state_from_issue(issue: dict) -> dict:
    """Parse YAML state from issue payload."""
    body = issue.get("body", "") or ""
    return parse_state_yaml_from_issue_body(body)


def get_state_issue_snapshot() -> StateIssueSnapshot | None:
    """Fetch state issue body plus metadata for state writes."""
    if not STATE_ISSUE_NUMBER:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return None

    response = github_api_request(
        "GET",
        f"issues/{STATE_ISSUE_NUMBER}",
        suppress_error_log=True,
    )
    if response.status_code != 200:
        print(
            "ERROR: Failed to fetch state issue "
            f"#{STATE_ISSUE_NUMBER} (status {response.status_code}): {response.text}",
            file=sys.stderr,
        )
        return None

    if not isinstance(response.payload, dict):
        print("ERROR: State issue response payload was not an object", file=sys.stderr)
        return None

    body = response.payload.get("body")
    if not isinstance(body, str):
        body = ""

    html_url = response.payload.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        repo = f"{os.environ.get('REPO_OWNER', '')}/{os.environ.get('REPO_NAME', '')}".strip("/")
        html_url = f"https://github.com/{repo}/issues/{STATE_ISSUE_NUMBER}" if repo else ""

    return StateIssueSnapshot(
        body=body,
        etag=response.headers.get("etag"),
        html_url=html_url,
    )


def conditional_patch_state_issue(body: str, etag: str | None = None) -> GitHubApiResult:
    """Patch state issue body.

    The `etag` argument is retained for compatibility with tests and call sites,
    but state serialization is handled by the dedicated lock backend.
    """
    return github_api_request(
        "PATCH",
        f"issues/{STATE_ISSUE_NUMBER}",
        {"body": body},
        suppress_error_log=True,
    )


def assert_lock_held(operation: str) -> None:
    """Fail fast when mutating state outside the lock boundary."""
    if ACTIVE_LEASE_CONTEXT is None:
        raise RuntimeError(f"Mutating path reached without lease lock: {operation}")


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
    assert_lock_held("save_state")

    if not STATE_ISSUE_NUMBER:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return False

    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    for attempt in range(1, LOCK_API_RETRY_LIMIT + 1):
        if not ensure_state_issue_lease_lock_fresh():
            print("ERROR: Failed to refresh reviewer-bot lease lock before save", file=sys.stderr)
            return False

        snapshot = get_state_issue_snapshot()
        if snapshot is None:
            return False

        lock_meta = parse_lock_metadata_from_issue_body(snapshot.body)
        body = render_state_issue_body(state, lock_meta, snapshot.body)

        response = conditional_patch_state_issue(body, snapshot.etag)
        if response.status_code == 200:
            print(f"State saved to issue #{STATE_ISSUE_NUMBER}")
            return True

        if response.status_code in {409, 412}:
            print(
                "WARNING: State save hit conflict "
                f"(status {response.status_code}); retrying ({attempt}/{LOCK_API_RETRY_LIMIT})",
                file=sys.stderr,
            )
            delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
            time.sleep(delay)
            continue

        if response.status_code == 404:
            print(
                f"ERROR: State issue #{STATE_ISSUE_NUMBER} not found during save_state",
                file=sys.stderr,
            )
            return False

        if response.status_code in {401, 403}:
            print(
                "ERROR: Permission failure while saving state issue "
                f"#{STATE_ISSUE_NUMBER} (status {response.status_code}): {response.text}",
                file=sys.stderr,
            )
            return False

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < LOCK_API_RETRY_LIMIT:
                delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                print(
                    "WARNING: Retryable state issue write failure "
                    f"(status {response.status_code}); retrying ({attempt}/{LOCK_API_RETRY_LIMIT})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            print(
                "ERROR: Exhausted retries while saving state issue "
                f"#{STATE_ISSUE_NUMBER}; last status {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            return False

        print(
            f"ERROR: Unexpected status {response.status_code} while saving state issue: {response.text}",
            file=sys.stderr,
        )
        return False

    print(
        f"ERROR: Failed to save state to issue #{STATE_ISSUE_NUMBER} after retries",
        file=sys.stderr,
    )
    return False


def parse_iso8601_timestamp(value: Any) -> datetime | None:
    """Parse an ISO8601 timestamp and normalize to UTC timezone."""
    if not isinstance(value, str) or not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def lock_is_currently_valid(lock_meta: dict, now: datetime | None = None) -> bool:
    """Return True when lock metadata contains a non-expired lease token."""
    if not isinstance(lock_meta, dict):
        return False

    if lock_meta.get("lock_state") != "locked":
        return False

    lock_token = lock_meta.get("lock_token")
    if not isinstance(lock_token, str) or not lock_token:
        return False

    expires_at = parse_iso8601_timestamp(lock_meta.get("lock_expires_at"))
    if expires_at is None:
        return False

    now = now or datetime.now(timezone.utc)
    return expires_at > now


def get_lock_owner_context() -> tuple[str, str, str]:
    """Get lock owner identity from workflow context."""
    run_id = (
        os.environ.get("WORKFLOW_RUN_ID", "").strip()
        or os.environ.get("GITHUB_RUN_ID", "").strip()
        or "local-run"
    )
    workflow = (
        os.environ.get("WORKFLOW_NAME", "").strip()
        or os.environ.get("GITHUB_WORKFLOW", "").strip()
        or "reviewer-bot"
    )
    job = (
        os.environ.get("WORKFLOW_JOB_NAME", "").strip()
        or os.environ.get("GITHUB_JOB", "").strip()
        or "reviewer-bot"
    )
    return run_id, workflow, job


def build_lock_metadata(
    lock_token: str,
    lock_owner_run_id: str,
    lock_owner_workflow: str,
    lock_owner_job: str,
) -> dict:
    """Build normalized lock metadata document."""
    acquired_at = datetime.now(timezone.utc)
    expires_at = acquired_at.timestamp() + LOCK_LEASE_TTL_SECONDS
    return normalize_lock_metadata(
        {
            "schema_version": LOCK_SCHEMA_VERSION,
            "lock_state": "locked",
            "lock_owner_run_id": lock_owner_run_id,
            "lock_owner_workflow": lock_owner_workflow,
            "lock_owner_job": lock_owner_job,
            "lock_token": lock_token,
            "lock_acquired_at": acquired_at.isoformat(),
            "lock_expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
    )


def clear_lock_metadata() -> dict:
    """Return normalized empty lock metadata."""
    return normalize_lock_metadata(
        {
            "schema_version": LOCK_SCHEMA_VERSION,
            "lock_state": "unlocked",
        }
    )


def normalize_lock_ref_name(ref_name: str) -> str:
    """Normalize lock ref name to REST API path form (without refs/ prefix)."""
    normalized = ref_name.strip()
    if normalized.startswith("refs/"):
        normalized = normalized[len("refs/") :]
    if not normalized:
        normalized = "heads/reviewer-bot-state-lock"
    return normalized


def get_lock_ref_name() -> str:
    """Return normalized lock ref name."""
    return normalize_lock_ref_name(LOCK_REF_NAME)


def get_lock_ref_display() -> str:
    """Return full lock ref for logs."""
    return f"refs/{get_lock_ref_name()}"


def get_state_issue_html_url() -> str:
    """Build canonical state issue URL for diagnostics."""
    repo = f"{os.environ.get('REPO_OWNER', '')}/{os.environ.get('REPO_NAME', '')}".strip("/")
    if not repo or not STATE_ISSUE_NUMBER:
        return ""
    return f"https://github.com/{repo}/issues/{STATE_ISSUE_NUMBER}"


def extract_ref_sha(payload: Any) -> str | None:
    """Extract git ref target SHA from API payload."""
    if not isinstance(payload, dict):
        return None
    obj = payload.get("object")
    if isinstance(obj, dict):
        sha = obj.get("sha")
        if isinstance(sha, str) and sha:
            return sha
    sha = payload.get("sha")
    if isinstance(sha, str) and sha:
        return sha
    return None


def extract_commit_tree_sha(payload: Any) -> str | None:
    """Extract commit tree SHA from API payload."""
    if not isinstance(payload, dict):
        return None
    tree = payload.get("tree")
    if not isinstance(tree, dict):
        return None
    tree_sha = tree.get("sha")
    if isinstance(tree_sha, str) and tree_sha:
        return tree_sha
    return None


def extract_commit_sha(payload: Any) -> str | None:
    """Extract commit SHA from API payload."""
    if not isinstance(payload, dict):
        return None
    sha = payload.get("sha")
    if isinstance(sha, str) and sha:
        return sha
    return None


def render_lock_commit_message(lock_meta: dict) -> str:
    """Render lock metadata into a deterministic commit message payload."""
    normalized = normalize_lock_metadata(lock_meta)
    payload = json.dumps(normalized, sort_keys=True)
    return f"{LOCK_COMMIT_MARKER}\n{payload}\n"


def parse_lock_metadata_from_lock_commit_message(message: str) -> dict:
    """Parse lock metadata from lock commit message."""
    if not isinstance(message, str):
        return clear_lock_metadata()

    lines = message.splitlines()
    if not lines:
        return clear_lock_metadata()

    if lines[0].strip() != LOCK_COMMIT_MARKER:
        return clear_lock_metadata()

    payload = "\n".join(lines[1:]).strip()
    if not payload:
        return clear_lock_metadata()

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return clear_lock_metadata()

    if not isinstance(parsed, dict):
        return clear_lock_metadata()
    return normalize_lock_metadata(parsed)


def ensure_lock_ref_exists() -> str:
    """Ensure lock ref exists and return current head SHA."""
    lock_ref = get_lock_ref_name()
    get_response = github_api_request("GET", f"git/ref/{lock_ref}", suppress_error_log=True)
    if get_response.status_code == 200:
        ref_sha = extract_ref_sha(get_response.payload)
        if ref_sha:
            return ref_sha
        raise RuntimeError("Lock ref GET returned success but no SHA")

    if get_response.status_code not in {404}:
        raise RuntimeError(
            "Failed to read reviewer-bot lock ref "
            f"{get_lock_ref_display()} (status {get_response.status_code}): {get_response.text}"
        )

    base_branch = LOCK_REF_BOOTSTRAP_BRANCH.strip() or "main"
    base_response = github_api_request(
        "GET",
        f"git/ref/heads/{base_branch}",
        suppress_error_log=True,
    )
    if base_response.status_code != 200:
        raise RuntimeError(
            "Failed to bootstrap reviewer-bot lock ref from "
            f"heads/{base_branch} (status {base_response.status_code}): {base_response.text}"
        )

    base_sha = extract_ref_sha(base_response.payload)
    if not base_sha:
        raise RuntimeError("Bootstrap branch ref response missing SHA")

    create_response = github_api_request(
        "POST",
        "git/refs",
        {
            "ref": f"refs/{lock_ref}",
            "sha": base_sha,
        },
        suppress_error_log=True,
    )
    if create_response.status_code not in {201, 422}:
        raise RuntimeError(
            "Failed to create reviewer-bot lock ref "
            f"{get_lock_ref_display()} (status {create_response.status_code}): {create_response.text}"
        )

    refresh_response = github_api_request("GET", f"git/ref/{lock_ref}", suppress_error_log=True)
    if refresh_response.status_code != 200:
        raise RuntimeError(
            "Unable to read reviewer-bot lock ref after create "
            f"(status {refresh_response.status_code}): {refresh_response.text}"
        )

    ref_sha = extract_ref_sha(refresh_response.payload)
    if not ref_sha:
        raise RuntimeError("Reviewer-bot lock ref exists but SHA was missing")
    return ref_sha


def get_lock_ref_snapshot() -> tuple[str, str, dict]:
    """Return lock ref head SHA, tree SHA, and parsed lock metadata."""
    ref_sha = ensure_lock_ref_exists()
    commit_response = github_api_request(
        "GET",
        f"git/commits/{ref_sha}",
        suppress_error_log=True,
    )
    if commit_response.status_code != 200:
        raise RuntimeError(
            "Failed to read lock commit "
            f"{ref_sha} (status {commit_response.status_code}): {commit_response.text}"
        )

    if not isinstance(commit_response.payload, dict):
        raise RuntimeError("Lock commit response payload was not a JSON object")

    tree_sha = extract_commit_tree_sha(commit_response.payload)
    if not tree_sha:
        raise RuntimeError("Lock commit payload missing tree SHA")

    message = commit_response.payload.get("message")
    if not isinstance(message, str):
        message = ""

    lock_meta = parse_lock_metadata_from_lock_commit_message(message)
    return ref_sha, tree_sha, lock_meta


def create_lock_commit(parent_sha: str, tree_sha: str, lock_meta: dict) -> GitHubApiResult:
    """Create lock state commit that references existing tree."""
    return github_api_request(
        "POST",
        "git/commits",
        {
            "message": render_lock_commit_message(lock_meta),
            "tree": tree_sha,
            "parents": [parent_sha],
        },
        suppress_error_log=True,
    )


def cas_update_lock_ref(new_sha: str) -> GitHubApiResult:
    """Update lock ref with fast-forward (CAS-like) semantics."""
    return github_api_request(
        "PATCH",
        f"git/refs/{get_lock_ref_name()}",
        {
            "sha": new_sha,
            "force": False,
        },
        suppress_error_log=True,
    )


def ensure_state_issue_lease_lock_fresh() -> bool:
    """Renew lock if expiration is near while this run still owns it."""
    context = ACTIVE_LEASE_CONTEXT
    if context is None:
        return False

    if not context.lock_expires_at:
        return True

    expires_at = parse_iso8601_timestamp(context.lock_expires_at)
    if expires_at is None:
        return renew_state_issue_lease_lock(context)

    remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    if remaining_seconds > LOCK_RENEWAL_WINDOW_SECONDS:
        return True

    print(
        "Reviewer-bot lease lock nearing expiry; attempting renewal "
        f"(remaining={int(remaining_seconds)}s, token_prefix={context.lock_token[:8]})"
    )
    return renew_state_issue_lease_lock(context)


def renew_state_issue_lease_lock(context: LeaseContext) -> bool:
    """Renew currently held lock lease by appending refreshed lock commit."""
    for attempt in range(1, LOCK_API_RETRY_LIMIT + 1):
        try:
            ref_head_sha, tree_sha, current_lock = get_lock_ref_snapshot()
        except RuntimeError as exc:
            print(f"ERROR: Failed to read lock snapshot during renewal: {exc}", file=sys.stderr)
            return False

        current_token = current_lock.get("lock_token")
        if current_token != context.lock_token:
            print(
                "ERROR: Cannot renew reviewer-bot lock due to token mismatch "
                f"(expected prefix={context.lock_token[:8]}, got prefix={str(current_token)[:8]})",
                file=sys.stderr,
            )
            return False

        desired_lock = build_lock_metadata(
            context.lock_token,
            context.lock_owner_run_id,
            context.lock_owner_workflow,
            context.lock_owner_job,
        )

        create_response = create_lock_commit(ref_head_sha, tree_sha, desired_lock)
        if create_response.status_code != 201:
            if create_response.status_code == 429 or create_response.status_code >= 500:
                delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                print(
                    "Retryable lease lock renewal commit failure "
                    f"(status {create_response.status_code}); retrying "
                    f"({attempt}/{LOCK_API_RETRY_LIMIT})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            print(
                "ERROR: Failed to create lock renewal commit "
                f"(status {create_response.status_code}): {create_response.text}",
                file=sys.stderr,
            )
            return False

        new_commit_sha = extract_commit_sha(create_response.payload)
        if not new_commit_sha:
            print("ERROR: Lock renewal commit response missing SHA", file=sys.stderr)
            return False

        update_response = cas_update_lock_ref(new_commit_sha)
        if update_response.status_code == 200:
            context.lock_expires_at = desired_lock.get("lock_expires_at")
            print(
                "Renewed reviewer-bot lease lock "
                f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]})"
            )
            return True

        if update_response.status_code in {409, 422, 429} or update_response.status_code >= 500:
            delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
            print(
                "Retryable lease lock renewal ref update failure "
                f"(status {update_response.status_code}); retrying "
                f"({attempt}/{LOCK_API_RETRY_LIMIT})",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue

        print(
            "ERROR: Failed to update lock ref during renewal "
            f"(status {update_response.status_code}): {update_response.text}",
            file=sys.stderr,
        )
        return False

    print("ERROR: Exhausted retries while renewing reviewer-bot lease lock", file=sys.stderr)
    return False


def acquire_state_issue_lease_lock() -> LeaseContext:
    """Acquire durable lease lock using git-ref CAS updates."""
    global ACTIVE_LEASE_CONTEXT

    if ACTIVE_LEASE_CONTEXT is not None:
        return ACTIVE_LEASE_CONTEXT

    lock_token = uuid.uuid4().hex
    lock_owner_run_id, lock_owner_workflow, lock_owner_job = get_lock_owner_context()
    wait_started_at = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        elapsed = time.monotonic() - wait_started_at
        if elapsed > LOCK_MAX_WAIT_SECONDS:
            raise RuntimeError(
                "Timed out waiting for reviewer-bot lease lock "
                f"after {int(elapsed)}s (run_id={lock_owner_run_id}, token_prefix={lock_token[:8]}, "
                f"lock_ref={get_lock_ref_display()})"
            )

        ref_head_sha, tree_sha, current_lock = get_lock_ref_snapshot()
        now = datetime.now(timezone.utc)
        lock_valid = lock_is_currently_valid(current_lock, now)

        if not lock_valid:
            desired_lock = build_lock_metadata(
                lock_token,
                lock_owner_run_id,
                lock_owner_workflow,
                lock_owner_job,
            )
            create_response = create_lock_commit(ref_head_sha, tree_sha, desired_lock)
            if create_response.status_code != 201:
                if create_response.status_code == 429 or create_response.status_code >= 500:
                    print(
                        "Retryable lease lock acquire commit failure "
                        f"(status {create_response.status_code}); retrying (attempt {attempt})"
                    )
                    delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                    time.sleep(delay)
                    continue
                if create_response.status_code in {401, 403}:
                    raise RuntimeError(
                        "Insufficient permission to create reviewer-bot lock commit "
                        f"(status {create_response.status_code}): {create_response.text}"
                    )
                raise RuntimeError(
                    "Unexpected status while creating reviewer-bot lock commit "
                    f"(status {create_response.status_code}): {create_response.text}"
                )

            new_commit_sha = extract_commit_sha(create_response.payload)
            if not new_commit_sha:
                raise RuntimeError("Lock acquire commit response did not include commit SHA")

            update_response = cas_update_lock_ref(new_commit_sha)
            if update_response.status_code == 200:
                ACTIVE_LEASE_CONTEXT = LeaseContext(
                    lock_token=lock_token,
                    lock_owner_run_id=lock_owner_run_id,
                    lock_owner_workflow=lock_owner_workflow,
                    lock_owner_job=lock_owner_job,
                    state_issue_url=get_state_issue_html_url(),
                    lock_ref=get_lock_ref_display(),
                    lock_expires_at=desired_lock.get("lock_expires_at"),
                )
                print(
                    "Acquired reviewer-bot lease lock "
                    f"(run_id={lock_owner_run_id}, token_prefix={lock_token[:8]}, "
                    f"lock_ref={get_lock_ref_display()})"
                )
                return ACTIVE_LEASE_CONTEXT

            if update_response.status_code in {409, 422}:
                print(
                    "Lease lock acquire conflict "
                    f"(status {update_response.status_code}); retrying (attempt {attempt})"
                )
            elif update_response.status_code == 404:
                raise RuntimeError(
                    f"Lock ref {get_lock_ref_display()} not found while acquiring lease lock"
                )
            elif update_response.status_code in {401, 403}:
                raise RuntimeError(
                    "Insufficient permission to acquire reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
            elif update_response.status_code == 429 or update_response.status_code >= 500:
                print(
                    "Retryable lease lock acquire failure "
                    f"(status {update_response.status_code}); retrying (attempt {attempt})"
                )
            else:
                raise RuntimeError(
                    "Unexpected status while acquiring reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
        else:
            lock_owner = current_lock.get("lock_owner_run_id") or "unknown"
            lock_expires_at = current_lock.get("lock_expires_at") or "unknown"
            print(
                "Reviewer-bot lease lock currently held by "
                f"run_id={lock_owner} until {lock_expires_at}; waiting "
                f"(lock_ref={get_lock_ref_display()})"
            )

        delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
        time.sleep(delay)


def release_state_issue_lease_lock() -> bool:
    """Release lease lock if currently owned by this run context."""
    global ACTIVE_LEASE_CONTEXT

    if ACTIVE_LEASE_CONTEXT is None:
        return True

    context = ACTIVE_LEASE_CONTEXT
    released = False

    try:
        for attempt in range(1, LOCK_API_RETRY_LIMIT + 1):
            try:
                ref_head_sha, tree_sha, current_lock = get_lock_ref_snapshot()
            except RuntimeError as exc:
                print(f"ERROR: Failed to read lock snapshot while releasing lock: {exc}", file=sys.stderr)
                break

            current_token = current_lock.get("lock_token")
            if current_token != context.lock_token:
                print(
                    "WARNING: Lease lock token mismatch during release; "
                    f"expected prefix={context.lock_token[:8]}, got prefix={str(current_token)[:8]}",
                    file=sys.stderr,
                )
                return False

            create_response = create_lock_commit(ref_head_sha, tree_sha, clear_lock_metadata())
            if create_response.status_code != 201:
                if create_response.status_code in {429} or create_response.status_code >= 500:
                    print(
                        "Retryable lease lock release commit failure "
                        f"(status {create_response.status_code}); retrying "
                        f"({attempt}/{LOCK_API_RETRY_LIMIT})",
                        file=sys.stderr,
                    )
                    delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                    time.sleep(delay)
                    continue
                print(
                    "ERROR: Failed to create lock release commit "
                    f"(status {create_response.status_code}): {create_response.text}",
                    file=sys.stderr,
                )
                break

            new_commit_sha = extract_commit_sha(create_response.payload)
            if not new_commit_sha:
                print("ERROR: Lock release commit response missing SHA", file=sys.stderr)
                break

            update_response = cas_update_lock_ref(new_commit_sha)

            if update_response.status_code == 200:
                released = True
                print(
                    "Released reviewer-bot lease lock "
                    f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]}, "
                    f"lock_ref={get_lock_ref_display()})"
                )
                return True

            if update_response.status_code in {409, 422, 429} or update_response.status_code >= 500:
                print(
                    "Retryable lease lock release failure "
                    f"(status {update_response.status_code}); retrying ({attempt}/{LOCK_API_RETRY_LIMIT})",
                    file=sys.stderr,
                )
                delay = LOCK_RETRY_BASE_SECONDS + random.uniform(0, LOCK_RETRY_BASE_SECONDS)
                time.sleep(delay)
                continue

            if update_response.status_code in {401, 403, 404}:
                print(
                    "ERROR: Hard failure releasing reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}",
                    file=sys.stderr,
                )
                break

            print(
                "ERROR: Unexpected status while releasing reviewer-bot lease lock "
                f"(status {update_response.status_code}): {update_response.text}",
                file=sys.stderr,
            )
            break

        return False
    finally:
        if not released:
            print(
                "ERROR: Lease lock release failed "
                f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]}, "
                f"state_issue_url={context.state_issue_url})",
                file=sys.stderr,
            )
        ACTIVE_LEASE_CONTEXT = None


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


def reposition_member_as_next(state: dict, username: str) -> bool:
    """
    Move a queue member to current_index so they're next up.
    
    Used when undoing or passing an assignment to maintain fairness -
    the person who didn't complete their assignment should be next,
    but people behind them in the queue shouldn't be pushed further back.
    
    Algorithm:
    1. Remove the user from their current position
    2. Adjust current_index if we removed before it
    3. Insert at current_index (so they're next up)
    
    Returns True if successful, False if user not in queue (e.g., went /away).
    """
    # Find the user
    user_index = None
    user_entry = None
    for i, member in enumerate(state["queue"]):
        if member["github"].lower() == username.lower():
            user_index = i
            user_entry = member
            break
    
    if user_entry is None:
        return False
    
    # Remove from current position
    state["queue"].pop(user_index)
    
    # Adjust current_index if we removed before it
    if user_index < state["current_index"]:
        state["current_index"] -= 1
    
    # Ensure current_index is valid after removal
    if state["queue"]:
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0
    
    # Insert at current_index (so they're next up)
    state["queue"].insert(state["current_index"], user_entry)
    
    return True


def process_pass_until_expirations(state: dict) -> tuple[dict, list[str]]:
    """
    Check for expired pass-until entries and restore them to the queue.

    Returning members are repositioned to be next up in the queue.

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
                # Restore to queue
                restored_member = {
                    "github": entry["github"],
                    "name": entry.get("name", entry["github"]),
                }
                
                # Add to end of queue, then reposition as next
                state["queue"].append(restored_member)
                reposition_member_as_next(state, entry["github"])
                
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

4. When ready, **add the `sign-off: create pr` label** to signal the contributor should create a PR

## Bot Commands

If you need to pass this review:
- `{BOT_MENTION} /pass [reason]` - Pass just this issue to the next reviewer
- `{BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from the queue until a date
- `{BOT_MENTION} /release [reason]` - Release your own assignment and leave this issue unassigned
- `{BOT_MENTION} /release @username [reason]` - Release another reviewer's assignment (triage+ required)

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
- `{BOT_MENTION} /release [reason]` - Release your own assignment and leave this issue unassigned
- `{BOT_MENTION} /release @username [reason]` - Release another reviewer's assignment (triage+ required)

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
- `{BOT_MENTION} /release [reason]` - Release your own assignment and leave this PR unassigned
- `{BOT_MENTION} /release @username [reason]` - Release another reviewer's assignment (triage+ required)

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


# ==============================================================================
# Command Parsing & Handling
# ==============================================================================


def strip_code_blocks(comment_body: str) -> str:
    """Remove fenced, indented, and inline code blocks from text."""
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


def parse_command(comment_body: str) -> tuple[str, list[str]] | None:
    """
    Parse a bot command from a comment body.

    Returns (command, args) or None if no command found.

    Special return values:
    - ("_multiple_commands", []) - Multiple commands found in a single comment
    - ("_malformed_known", [attempted_cmd]) - Missing / prefix on known command
    - ("_malformed_unknown", [attempted_word]) - Missing / prefix on unknown word

    All commands must be prefixed with @guidelines-bot /<command>:
    - @guidelines-bot /pass [reason]
    - @guidelines-bot /r? @username (assign specific user)
    - @guidelines-bot /r? producers (assign next from queue)
    """
    # Look for @guidelines-bot /<command> pattern (correct syntax)
    mention_pattern = rf"{re.escape(BOT_MENTION)}\s+/\S+"
    pattern = rf"{re.escape(BOT_MENTION)}\s+/(\S+)(.*)$"
    matches = re.findall(mention_pattern, comment_body, re.IGNORECASE | re.MULTILINE)

    if len(matches) > 1:
        return "_multiple_commands", []

    match = re.search(pattern, comment_body, re.IGNORECASE | re.MULTILINE)

    if not match:
        # Check for malformed command (missing / prefix)
        malformed_pattern = rf"{re.escape(BOT_MENTION)}\s+(\S+)"
        malformed_match = re.search(malformed_pattern, comment_body, re.IGNORECASE | re.MULTILINE)

        if malformed_match:
            attempted = malformed_match.group(1).lower()
            # Check if it looks like a command (not just random text after mention)
            # Ignore if it starts with common conversational words
            conversational = {"i", "we", "you", "the", "a", "an", "is", "are", "can", "could",
                            "would", "should", "please", "thanks", "thank", "hi", "hello", "hey"}
            if attempted in conversational:
                return None

            # Check if it's a known command without the /
            if attempted in COMMANDS or attempted in {"r?-user", "assign-from-queue"}:
                return "_malformed_known", [attempted]
            else:
                return "_malformed_unknown", [attempted]

        return None

    command = match.group(1).lower()
    args_str = match.group(2).strip()

    # Special handling for "/r? <target>" syntax
    if command == "r?":
        target = args_str.split()[0] if args_str else ""
        if target.lower() == "producers":
            return "assign-from-queue", []
        elif target:
            username = target.lstrip("@")
            return "r?-user", [f"@{username}"]
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
    The passer is repositioned to be next up for future issues.

    Returns (response_message, success).
    """
    # Get or create the tracking entry for this issue
    issue_data = ensure_review_entry(state, issue_number, create=True)
    if issue_data is None:
        return "❌ Unable to load review state.", False
    
    # Determine who the current reviewer is:
    # 1. First check our tracked state
    # 2. Fall back to GitHub assignees
    passed_reviewer = issue_data.get("current_reviewer")
    if not passed_reviewer:
        current_assignees = get_issue_assignees(issue_number)
        passed_reviewer = current_assignees[0] if current_assignees else None

    if not passed_reviewer:
        return "❌ No reviewer is currently assigned to pass.", False

    if passed_reviewer.lower() != comment_author.lower():
        return "❌ Only the currently assigned reviewer can use `/pass`.", False


    # Check if this is the first pass on this issue (for messaging only)
    is_first_pass = len(issue_data["skipped"]) == 0
    
    # Record this reviewer as having passed on this issue
    if passed_reviewer not in issue_data["skipped"]:
        issue_data["skipped"].append(passed_reviewer)

    # Get the issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")

    # Build skip set: everyone who has passed on this issue + issue author
    skip_set = set(issue_data["skipped"])
    if issue_author:
        skip_set.add(issue_author)

    # Find next reviewer, skipping all who have passed
    # This advances current_index past the substitute
    next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not next_reviewer:
        return ("❌ No other reviewers available. Everyone in the queue has either "
                "passed on this issue or is the author."), False

    # Reposition the passer to be next up for future issues
    # (get_next_reviewer already advanced the index past the substitute)
    reposition_member_as_next(state, passed_reviewer)

    # Unassign the passed reviewer first (best effort - may fail if no permissions)
    unassign_reviewer(issue_number, passed_reviewer)

    # Assign the substitute to this issue.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, next_reviewer)
    
    # Track the new reviewer in our state (this is the source of truth)
    set_current_reviewer(state, issue_number, next_reviewer)

    # Record the assignment
    record_assignment(state, next_reviewer, issue_number, "pr" if is_pr else "issue")

    assignment_line = f"@{next_reviewer} is now assigned as the reviewer."
    if not assignment_attempt.success:
        failure_comment = get_assignment_failure_comment(next_reviewer, assignment_attempt)
        if failure_comment:
            assignment_line = failure_comment
        else:
            status_text = assignment_attempt.status_code or "unknown"
            assignment_line = (
                f"@{next_reviewer} is designated as reviewer in bot state, but GitHub "
                f"assignment could not be confirmed (status {status_text})."
            )

    reason_text = f" Reason: {reason}" if reason else ""
    if is_first_pass:
        return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n"
                f"{assignment_line}\n\n"
                f"_@{passed_reviewer} is next in queue for future issues._"), True
    else:
        # Get the original passer (first in the skip list)
        original_passer = issue_data["skipped"][0]
        return (f"✅ @{passed_reviewer} has passed this review.{reason_text}\n\n"
                f"{assignment_line}\n\n"
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
            assignment_attempt = request_reviewer_assignment(issue_number, next_reviewer)
            set_current_reviewer(state, issue_number, next_reviewer)
            record_assignment(state, next_reviewer, issue_number,
                            "pr" if is_pr else "issue")
            if assignment_attempt.success:
                reassigned_msg = f"\n\n@{next_reviewer} has been assigned as the new reviewer for this issue."
            else:
                failure_comment = get_assignment_failure_comment(next_reviewer, assignment_attempt)
                if failure_comment:
                    reassigned_msg = f"\n\n{failure_comment}"
                else:
                    status_text = assignment_attempt.status_code or "unknown"
                    reassigned_msg = (
                        "\n\n"
                        f"@{next_reviewer} is designated as the new reviewer in bot state, but "
                        f"GitHub assignment is not confirmed (status {status_text})."
                    )
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
    
    # Find +label and -label patterns where the operator starts a label token.
    # Operators must be at the start or preceded by whitespace to avoid splitting on hyphens.
    pattern = r'(?:(?<=^)|(?<=\s))([+-])(.+?)(?=\s[+-]|\s*$)'
    matches = re.findall(pattern, label_string)
    
    if not matches:
        return "❌ No valid labels found. Use `+label-name` to add or `-label-name` to remove.", False
    
    # Get existing repo labels to validate additions
    existing_labels = get_repo_labels()
    
    results = []
    all_success = True
    
    for action, label in matches:
        label = label.strip()
        if not label:
            continue
            
        if action == "+":
            # Check if label exists in repo before adding
            if label not in existing_labels:
                results.append(f"⚠️ Label `{label}` does not exist in this repository")
                all_success = False
            elif add_label(issue_number, label):
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


def parse_issue_labels() -> list[str]:
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        labels = []
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels]


def run_command(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Command failed").strip())
    return result


def summarize_output(result: subprocess.CompletedProcess, limit: int = 20) -> str:
    combined = "\n".join(
        [line for line in [result.stdout, result.stderr] if line]
    ).strip()
    if not combined:
        return ""
    lines = combined.splitlines()
    return "\n".join(lines[-limit:])


def list_changed_files(repo_root: Path) -> list[str]:
    result = run_command(["git", "status", "--porcelain"], cwd=repo_root)
    files = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ")[-1]
        files.append(path)
    return files


def get_default_branch() -> str:
    repo_info = github_api("GET", "")
    if isinstance(repo_info, dict):
        return repo_info.get("default_branch", "main")
    return "main"


def find_open_pr_for_branch(branch: str) -> dict | None:
    owner = os.environ.get("REPO_OWNER", "").strip()
    branch = branch.strip()
    if not owner or not branch:
        return None

    response = github_api("GET", f"pulls?state=open&head={owner}:{branch}")
    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict):
            return first
    return None


def resolve_workflow_run_pr_number() -> int:
    """Resolve and validate PR number for workflow_run reconcile execution."""
    pr_number_raw = os.environ.get("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "").strip()
    if not pr_number_raw:
        raise RuntimeError(
            "Missing WORKFLOW_RUN_RECONCILE_PR_NUMBER in workflow_run reconcile context"
        )

    try:
        pr_number = int(pr_number_raw)
    except ValueError as exc:
        raise RuntimeError(
            "WORKFLOW_RUN_RECONCILE_PR_NUMBER must be a positive integer"
        ) from exc

    if pr_number <= 0:
        raise RuntimeError(
            "WORKFLOW_RUN_RECONCILE_PR_NUMBER must be a positive integer"
        )

    reconcile_head_sha = os.environ.get("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "").strip()
    if not reconcile_head_sha:
        raise RuntimeError(
            "Missing WORKFLOW_RUN_RECONCILE_HEAD_SHA in workflow_run reconcile context"
        )

    workflow_run_head_sha = os.environ.get("WORKFLOW_RUN_HEAD_SHA", "").strip()
    if not workflow_run_head_sha:
        raise RuntimeError("Missing WORKFLOW_RUN_HEAD_SHA for workflow_run reconcile")

    if reconcile_head_sha != workflow_run_head_sha:
        raise RuntimeError(
            "Workflow_run reconcile context SHA mismatch between artifact and workflow payload"
        )

    pull_request = github_api("GET", f"pulls/{pr_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch pull request #{pr_number} during workflow_run reconcile")

    head = pull_request.get("head")
    pull_request_head_sha = ""
    if isinstance(head, dict):
        head_sha = head.get("sha")
        if isinstance(head_sha, str):
            pull_request_head_sha = head_sha.strip()

    if not pull_request_head_sha:
        raise RuntimeError(f"Pull request #{pr_number} is missing a valid head SHA")

    if pull_request_head_sha != reconcile_head_sha:
        raise RuntimeError(
            f"Pull request #{pr_number} head SHA does not match workflow_run reconcile context"
        )

    print(f"Resolved workflow_run PR from reconcile context: #{pr_number}")
    return pr_number


def create_pull_request(branch: str, base: str, issue_number: int) -> dict | None:
    existing = find_open_pr_for_branch(branch)
    if existing:
        return existing
    title = "chore: update spec.lock (no guideline impact)"
    body = (
        "Updates `src/spec.lock` after confirming the audit reported no affected guidelines.\n\n"
        f"Closes #{issue_number}"
    )
    response = github_api(
        "POST",
        "pulls",
        {
            "title": title,
            "head": branch,
            "base": base,
            "body": body,
        },
    )
    if isinstance(response, dict):
        return response
    return None


def handle_accept_no_fls_changes_command(issue_number: int, comment_author: str) -> tuple[str, bool]:
    if os.environ.get("IS_PULL_REQUEST", "false").lower() == "true":
        return "❌ This command can only be used on issues, not PRs.", False

    labels = parse_issue_labels()
    if FLS_AUDIT_LABEL not in labels:
        return "❌ This command is only available on issues labeled `fls-audit`.", False

    if not check_user_permission(comment_author, "triage"):
        return "❌ You must have triage permissions to run this command.", False

    repo_root = Path(__file__).resolve().parents[1]
    if list_changed_files(repo_root):
        return "❌ Working tree is not clean; refusing to update spec.lock.", False

    audit_result = run_command(
        ["uv", "run", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"],
        cwd=repo_root,
        check=False,
    )
    if audit_result.returncode == 2:
        return (
            "❌ The audit reports affected guidelines. Please review and open a PR with "
            "the necessary guideline updates instead.",
            False,
        )
    if audit_result.returncode != 0:
        details = summarize_output(audit_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return (f"❌ Audit command failed.{detail_text}", False)

    update_result = run_command(
        ["uv", "run", "python", "./make.py", "--update-spec-lock-file"],
        cwd=repo_root,
        check=False,
    )
    if update_result.returncode != 0:
        details = summarize_output(update_result)
        detail_text = f"\n\nDetails:\n```\n{details}\n```" if details else ""
        return (f"❌ Failed to update spec.lock.{detail_text}", False)

    changed_files = list_changed_files(repo_root)
    if not changed_files:
        return "✅ `src/spec.lock` is already up to date; no PR needed.", True

    unexpected = {path for path in changed_files if path != "src/spec.lock"}
    if unexpected:
        paths = ", ".join(sorted(unexpected))
        return (
            "❌ Unexpected tracked file changes detected; refusing to open a PR. "
            f"Please review: {paths}",
            False,
        )

    branch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_branch = get_default_branch()
    branch_name = f"chore/spec-lock-{branch_date}-issue-{issue_number}"
    if run_command(["git", "rev-parse", "--verify", branch_name], cwd=repo_root, check=False).returncode == 0:
        suffix = datetime.now(timezone.utc).strftime("%H%M%S")
        branch_name = f"{branch_name}-{suffix}"

    try:
        run_command(["git", "checkout", "-b", branch_name], cwd=repo_root)
        run_command(["git", "add", "src/spec.lock"], cwd=repo_root)
        run_command(
            [
                "git",
                "-c",
                "user.name=guidelines-bot",
                "-c",
                "user.email=guidelines-bot@users.noreply.github.com",
                "commit",
                "-m",
                "chore: update spec.lock; no affected guidelines",
            ],
            cwd=repo_root,
        )
        run_command(["git", "push", "origin", branch_name], cwd=repo_root)
    except RuntimeError as exc:
        return (f"❌ Failed to create branch or push changes: {exc}", False)

    pr = create_pull_request(branch_name, base_branch, issue_number)
    if not pr or "html_url" not in pr:
        return "❌ Failed to open a pull request for the spec.lock update.", False

    return (f"✅ Opened PR {pr['html_url']}", True)


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


def handle_queue_command(state: dict) -> tuple[str, bool]:
    """
    Handle the queue command - show current queue status.

    Returns (response_message, success).
    """
    queue_size = len(state["queue"])
    
    # Build link to state issue
    repo_owner = os.environ.get("REPO_OWNER", "")
    repo_name = os.environ.get("REPO_NAME", "")
    state_issue_link = ""
    if repo_owner and repo_name and STATE_ISSUE_NUMBER:
        state_issue_link = f"\n\n[View full state details](https://github.com/{repo_owner}/{repo_name}/issues/{STATE_ISSUE_NUMBER})"

    if queue_size == 0:
        return f"📊 **Queue Status**: No reviewers in queue.{state_issue_link}", True

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
            f"{away_text}{state_issue_link}"), True


def handle_commands_command() -> tuple[str, bool]:
    """
    Handle the status command - show all available commands.

    Returns (response_message, success).
    """
    return (f"ℹ️ **Available Commands**\n\n"
            f"**Pass or step away:**\n"
            f"- `{BOT_MENTION} /pass [reason]` - Pass this review to next in queue (current reviewer only)\n"
            f"- `{BOT_MENTION} /away YYYY-MM-DD [reason]` - Step away from queue until a date\n"
            f"- `{BOT_MENTION} /release [reason]` - Release your own assignment and leave this unassigned\n"
            f"- `{BOT_MENTION} /release @username [reason]` - Release another reviewer's assignment (triage+ required)\n\n"
            f"**Assign reviewers:**\n"
            f"- `{BOT_MENTION} /r? @username` - Assign a specific reviewer\n"
            f"- `{BOT_MENTION} /r? producers` - Request the next reviewer from the queue\n"
            f"- `{BOT_MENTION} /claim` - Claim this review for yourself\n\n"
        f"**Other:**\n"
        f"- `{BOT_MENTION} /label +label-name` - Add a label\n"
        f"- `{BOT_MENTION} /label -label-name` - Remove a label\n"
        f"- `{BOT_MENTION} /rectify` - Reconcile this issue/PR review state from GitHub\n"
        f"- `{BOT_MENTION} /accept-no-fls-changes` - Update spec.lock and open a PR when no guidelines are impacted\n"
        f"- `{BOT_MENTION} /queue` - Show current queue status\n"
        f"- `{BOT_MENTION} /sync-members` - Sync queue with members.md"), True


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
                f"Please use `{BOT_MENTION} /away YYYY-MM-DD` to update your return date first, "
                f"or wait until your scheduled return."), False

    # Get current assignees
    current_assignees = get_issue_assignees(issue_number)

    # Remove existing assignees
    for assignee in current_assignees:
        unassign_reviewer(issue_number, assignee)

    # Assign the claimer.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, comment_author)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, comment_author, assignment_method="claim")

    # Record the assignment
    record_assignment(state, comment_author, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    response = f"✅ @{comment_author} has claimed this review{prev_text}."
    if not assignment_attempt.success:
        failure_comment = get_assignment_failure_comment(comment_author, assignment_attempt)
        if failure_comment:
            response = f"{response}\n\n{failure_comment}"

    return response, True


def handle_release_command(state: dict, issue_number: int,
                          comment_author: str, args: list | None = None) -> tuple[str, bool]:
    """
    Handle the release command - release an assignment without auto-reassigning.

    Unlike pass, this does NOT automatically assign the next reviewer.
    Use this when you want to unassign yourself or someone else but leave it
    open for someone to claim.

    Syntax:
    - /release [reason] - Release yourself
    - /release @username [reason] - Release someone else (requires triage+ permission)

    Returns (response_message, success).
    """
    args = args or []
    
    # Determine if targeting self or someone else
    target_username = None
    reason = None
    releasing_other = False
    
    if args and args[0].startswith("@"):
        # Releasing someone else
        target_username = args[0].lstrip("@")
        reason = " ".join(args[1:]) if len(args) > 1 else None
        releasing_other = target_username.lower() != comment_author.lower()
        
        if releasing_other:
            # Check if comment author has triage+ permission
            if not check_user_permission(comment_author, "triage"):
                return (f"❌ @{comment_author} does not have permission to release "
                        f"other reviewers. Triage access or higher is required."), False
    else:
        # Releasing self (original behavior)
        target_username = comment_author
        reason = " ".join(args) if args else None
    
    # Check who the current reviewer is (from our state first, then GitHub)
    issue_key = str(issue_number)
    tracked_reviewer = None
    assignment_method = None
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        issue_data = state["active_reviews"][issue_key]
        if isinstance(issue_data, dict):
            tracked_reviewer = issue_data.get("current_reviewer")
            assignment_method = issue_data.get("assignment_method")
    
    # Also check GitHub assignees
    current_assignees = get_issue_assignees(issue_number)

    # Determine if the target is the current reviewer
    is_tracked = tracked_reviewer and tracked_reviewer.lower() == target_username.lower()
    is_assigned = target_username.lower() in [a.lower() for a in current_assignees]

    if not is_tracked and not is_assigned:
        if releasing_other:
            # Trying to release someone who isn't assigned
            if tracked_reviewer:
                return (f"❌ @{target_username} is not the current reviewer. "
                        f"Current reviewer: @{tracked_reviewer}"), False
            elif current_assignees:
                return (f"❌ @{target_username} is not assigned to this issue/PR. "
                        f"Current assignee(s): @{', @'.join(current_assignees)}"), False
            else:
                return f"❌ @{target_username} is not assigned to this issue/PR.", False
        else:
            # Trying to release self when not assigned
            if tracked_reviewer:
                return (f"❌ @{comment_author} is not the current reviewer. "
                        f"Current reviewer: @{tracked_reviewer}\n\n"
                        f"If you meant to release @{tracked_reviewer}, use "
                        f"`{BOT_MENTION} /release @{tracked_reviewer}` "
                        f"(triage+ required)."), False
            elif current_assignees:
                response = (f"❌ @{comment_author} is not assigned to this issue/PR. "
                            f"Current assignee(s): @{', @'.join(current_assignees)}")
                if len(current_assignees) == 1:
                    current_assignee = current_assignees[0]
                    response += (f"\n\nIf you meant to release @{current_assignee}, use "
                                 f"`{BOT_MENTION} /release @{current_assignee}` "
                                 f"(triage+ required).")
                return response, False
            else:
                return "❌ No reviewer is currently assigned to release.", False

    # Remove the assignment (best effort)
    unassign_reviewer(issue_number, target_username)

    # Clear the current reviewer in our state
    if "active_reviews" in state and issue_key in state["active_reviews"]:
        if isinstance(state["active_reviews"][issue_key], dict):
            state["active_reviews"][issue_key]["current_reviewer"] = None

    # If this was a round-robin assignment, reposition the released user in the queue
    # so they're next up (since they didn't complete the review they were assigned)
    # For 'claim' or 'manual' assignments, don't touch the queue - they volunteered
    # or were specifically requested
    if assignment_method == "round-robin":
        reposition_member_as_next(state, target_username)

    reason_text = f" Reason: {reason}" if reason else ""
    
    if releasing_other:
        # Someone else released this reviewer - notify them
        return (f"✅ @{comment_author} has released @{target_username} from this review.{reason_text}\n\n"
                f"_This issue/PR is now unassigned. Use `{BOT_MENTION} /r? producers` to assign "
                f"the next reviewer from the queue, or `{BOT_MENTION} /claim` to claim it._"), True
    else:
        # Self-release
        return (f"✅ @{target_username} has released this review.{reason_text}\n\n"
                f"_This issue/PR is now unassigned. Use `{BOT_MENTION} /r? producers` to assign "
                f"the next reviewer from the queue, or `{BOT_MENTION} /claim` to claim it._"), True


def handle_assign_command(state: dict, issue_number: int,
                         username: str) -> tuple[str, bool]:
    """
    Handle assigning a specific person as reviewer.

    Used by /r? @username command.

    Returns (response_message, success).
    """
    # Clean up username (remove @ if present)
    username = username.lstrip("@")

    if not username:
        return (f"❌ Missing username. Usage: `{BOT_MENTION} /r? @username`"), False

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

    # Assign the specified user.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, username)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, username, assignment_method="manual")

    # Record the assignment (but don't advance queue - this is manual assignment)
    record_assignment(state, username, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    if assignment_attempt.success:
        return f"✅ @{username} has been assigned as reviewer{prev_text}.", True

    response = (
        f"✅ @{username} remains designated as reviewer in bot state{prev_text}. "
        "GitHub reviewer assignment could not be completed."
    )
    failure_comment = get_assignment_failure_comment(username, assignment_attempt)
    if failure_comment:
        response = f"{response}\n\n{failure_comment}"

    return response, True


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
                f"Please use `{BOT_MENTION} /sync-members` to update the queue."), False

    # Assign the reviewer.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, next_reviewer)

    # Track the reviewer in our state (source of truth for pass command)
    set_current_reviewer(state, issue_number, next_reviewer)

    # Record the assignment
    record_assignment(state, next_reviewer, issue_number, "pr" if is_pr else "issue")

    if current_assignees:
        prev_text = f" (previously: @{', @'.join(current_assignees)})"
    else:
        prev_text = ""

    failure_comment = get_assignment_failure_comment(next_reviewer, assignment_attempt)
    if failure_comment:
        post_comment(issue_number, failure_comment)

    # Post the appropriate guidance
    if is_pr:
        if assignment_attempt.success:
            guidance = get_pr_guidance(next_reviewer, issue_author)
            post_comment(issue_number, guidance)
    else:
        guidance = get_issue_guidance(next_reviewer, issue_author)
        post_comment(issue_number, guidance)

    if assignment_attempt.success:
        return f"✅ @{next_reviewer} (next in queue) has been assigned as reviewer{prev_text}.", True

    return (
        f"✅ @{next_reviewer} remains designated as reviewer in bot state{prev_text}."
        " GitHub reviewer assignment could not be completed."
    ), True


# ==============================================================================
# Event Handlers
# ==============================================================================


def ensure_review_entry(state: dict, issue_number: int, create: bool = False) -> dict | None:
    """Ensure the active review entry exists and has required fields."""
    issue_key = str(issue_number)

    if "active_reviews" not in state:
        state["active_reviews"] = {}

    review_entry = state["active_reviews"].get(issue_key)
    if review_entry is None:
        if not create:
            return None
        review_entry = {
            "skipped": [],
            "current_reviewer": None,
            "assigned_at": None,
            "last_reviewer_activity": None,
            "transition_warning_sent": None,
            "assignment_method": None,
            "review_completed_at": None,
            "review_completed_by": None,
            "review_completion_source": None,
            "mandatory_approver_required": False,
            "mandatory_approver_label_applied_at": None,
            "mandatory_approver_pinged_at": None,
            "mandatory_approver_satisfied_by": None,
            "mandatory_approver_satisfied_at": None,
        }
        state["active_reviews"][issue_key] = review_entry
    elif isinstance(review_entry, list):
        review_entry = {
            "skipped": review_entry,
            "current_reviewer": None,
            "assigned_at": None,
            "last_reviewer_activity": None,
            "transition_warning_sent": None,
            "assignment_method": None,
            "review_completed_at": None,
            "review_completed_by": None,
            "review_completion_source": None,
            "mandatory_approver_required": False,
            "mandatory_approver_label_applied_at": None,
            "mandatory_approver_pinged_at": None,
            "mandatory_approver_satisfied_by": None,
            "mandatory_approver_satisfied_at": None,
        }
        state["active_reviews"][issue_key] = review_entry

    if not isinstance(review_entry, dict):
        return None

    if not isinstance(review_entry.get("skipped"), list):
        review_entry["skipped"] = []

    required_fields = {
        "current_reviewer": None,
        "assigned_at": None,
        "last_reviewer_activity": None,
        "transition_warning_sent": None,
        "assignment_method": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "mandatory_approver_required": False,
        "mandatory_approver_label_applied_at": None,
        "mandatory_approver_pinged_at": None,
        "mandatory_approver_satisfied_by": None,
        "mandatory_approver_satisfied_at": None,
    }

    for field, default in required_fields.items():
        if field not in review_entry:
            review_entry[field] = default

    return review_entry


def set_current_reviewer(state: dict, issue_number: int, reviewer: str,
                        assignment_method: str = "round-robin") -> None:
    """Track the designated reviewer for an issue/PR in our state.
    
    Args:
        state: Bot state dict
        issue_number: Issue/PR number
        reviewer: GitHub username of the reviewer
        assignment_method: How they were assigned - 'round-robin', 'claim', or 'manual'
    """
    now = datetime.now(timezone.utc).isoformat()

    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return

    # Set the reviewer and timestamps
    review_data["current_reviewer"] = reviewer
    review_data["assigned_at"] = now
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None  # Clear any previous warning
    review_data["assignment_method"] = assignment_method
    review_data["review_completed_at"] = None
    review_data["review_completed_by"] = None
    review_data["review_completion_source"] = None
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_label_applied_at"] = None
    review_data["mandatory_approver_pinged_at"] = None
    review_data["mandatory_approver_satisfied_by"] = None
    review_data["mandatory_approver_satisfied_at"] = None


def update_reviewer_activity(state: dict, issue_number: int, reviewer: str) -> bool:
    """
    Update the last activity timestamp when the current reviewer comments.
    
    Returns True if activity was recorded (reviewer matched), False otherwise.
    """
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return False

    if review_data.get("review_completed_at"):
        return False
    
    current_reviewer = review_data.get("current_reviewer")
    if not current_reviewer or current_reviewer.lower() != reviewer.lower():
        return False
    
    # Update activity timestamp and clear any transition warning
    now = datetime.now(timezone.utc).isoformat()
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None
    
    print(f"Updated reviewer activity for #{issue_number} by @{reviewer}")
    return True


def mark_review_complete(
    state: dict,
    issue_number: int,
    reviewer: str | None,
    source: str,
) -> bool:
    """Mark a review as complete and stop reminder timers."""
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False

    if review_data.get("review_completed_at"):
        return False

    now = datetime.now(timezone.utc).isoformat()
    review_data["review_completed_at"] = now
    review_data["review_completed_by"] = reviewer or None
    review_data["review_completion_source"] = source
    review_data["last_reviewer_activity"] = now
    review_data["transition_warning_sent"] = None

    reviewer_text = f" by @{reviewer}" if reviewer else ""
    print(f"Marked review complete for #{issue_number}{reviewer_text} ({source})")
    return True


def is_triage_or_higher(username: str) -> bool:
    """Return True when user has triage+ permissions."""
    return check_user_permission(username, "triage")


def trigger_mandatory_approver_escalation(state: dict, issue_number: int) -> bool:
    """Open mandatory triage-approval escalation for a PR review cycle."""
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False

    now = datetime.now(timezone.utc).isoformat()
    state_changed = False

    if not review_data.get("mandatory_approver_required"):
        review_data["mandatory_approver_required"] = True
        review_data["mandatory_approver_satisfied_by"] = None
        review_data["mandatory_approver_satisfied_at"] = None
        state_changed = True

    label_ensure_ok = ensure_label_exists(MANDATORY_TRIAGE_APPROVER_LABEL)
    if label_ensure_ok:
        try:
            if add_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL):
                if review_data.get("mandatory_approver_label_applied_at") is None:
                    review_data["mandatory_approver_label_applied_at"] = now
                    state_changed = True
        except RuntimeError as exc:
            print(
                f"WARNING: Unable to apply escalation label on #{issue_number}: {exc}",
                file=sys.stderr,
            )
    else:
        print(
            "WARNING: Escalation label ensure/create failed; proceeding with comment-only escalation",
            file=sys.stderr,
        )

    if review_data.get("mandatory_approver_pinged_at") is None:
        if post_comment(issue_number, MANDATORY_TRIAGE_ESCALATION_TEMPLATE):
            review_data["mandatory_approver_pinged_at"] = now
            state_changed = True

    return state_changed


def satisfy_mandatory_approver_requirement(
    state: dict,
    issue_number: int,
    approver: str,
) -> bool:
    """Close mandatory triage escalation after first triage+ approval."""
    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False

    if not review_data.get("mandatory_approver_required"):
        return False

    if review_data.get("mandatory_approver_satisfied_at"):
        return False

    now = datetime.now(timezone.utc).isoformat()
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_satisfied_by"] = approver
    review_data["mandatory_approver_satisfied_at"] = now

    try:
        remove_label_with_status(issue_number, MANDATORY_TRIAGE_APPROVER_LABEL)
    except RuntimeError as exc:
        print(
            f"WARNING: Unable to remove escalation label on #{issue_number}: {exc}",
            file=sys.stderr,
        )

    post_comment(issue_number, MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver=approver))
    return True


def handle_pr_approved_review(
    state: dict,
    issue_number: int,
    review_author: str,
    completion_source: str,
) -> bool:
    """Apply approval transitions for designated and mandatory triage flows."""
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        print(f"No active review entry for #{issue_number}")
        return False

    current_reviewer = review_data.get("current_reviewer")
    author_is_designated = (
        isinstance(current_reviewer, str)
        and current_reviewer.lower() == review_author.lower()
    )

    author_is_triage = is_triage_or_higher(review_author)
    state_changed = False

    if author_is_designated:
        if mark_review_complete(state, issue_number, review_author, completion_source):
            state_changed = True

        if author_is_triage:
            if satisfy_mandatory_approver_requirement(state, issue_number, review_author):
                state_changed = True
            return state_changed

        if trigger_mandatory_approver_escalation(state, issue_number):
            state_changed = True
        return state_changed

    if review_data.get("mandatory_approver_required") and author_is_triage:
        if satisfy_mandatory_approver_requirement(state, issue_number, review_author):
            state_changed = True
        return state_changed

    print(
        f"Ignoring approved review from @{review_author} on #{issue_number}; "
        f"designated reviewer is @{current_reviewer}"
    )
    return state_changed


def parse_github_timestamp(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp string into a datetime."""
    if not isinstance(value, str) or not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_pull_request_reviews(issue_number: int) -> list[dict] | None:
    """Fetch submitted reviews for a pull request."""
    result = github_api("GET", f"pulls/{issue_number}/reviews?per_page=100")
    if result is None:
        return None
    if not isinstance(result, list):
        return []
    return [review for review in result if isinstance(review, dict)]


def get_latest_review_by_reviewer(reviews: list[dict], reviewer: str) -> dict | None:
    """Return the latest review authored by the given reviewer."""
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), -1)

    for index, review in enumerate(reviews):
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue

        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            submitted_at = datetime.min.replace(tzinfo=timezone.utc)

        review_key = (submitted_at, index)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review

    return latest_review


def find_triage_approval_after(
    reviews: list[dict],
    since: datetime | None,
) -> tuple[str, datetime] | None:
    """Find the first triage+ approval submitted after `since`."""
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[datetime, int, str]] = []

    for index, review in enumerate(reviews):
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue

        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue

        submitted_at = parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue

        if since is not None and submitted_at <= since:
            continue

        approvals.append((submitted_at, index, author))

    approvals.sort(key=lambda item: (item[0], item[1]))

    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at

    return None


def reconcile_active_review_entry(
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    """Reconcile one active review entry from current GitHub PR review state.

    Returns (message, success, state_changed).
    """
    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False

    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return (
            f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.",
            True,
            False,
        )

    if review_data.get("review_completed_at") and not review_data.get("mandatory_approver_required"):
        return f"ℹ️ Review for #{issue_number} is already marked complete; no changes made.", True, False

    if require_pull_request_context:
        is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
        if not is_pr:
            return (
                f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only "
                "reconciles PR reviews.",
                True,
                False,
            )

    reviews = get_pull_request_reviews(issue_number)
    if reviews is None:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False

    state_changed = False
    messages: list[str] = []

    latest_review = get_latest_review_by_reviewer(reviews, assigned_reviewer)
    if latest_review is None:
        messages.append(
            f"No review by assigned reviewer @{assigned_reviewer} was found on PR #{issue_number}."
        )
    else:
        latest_state = str(latest_review.get("state", "")).upper()
        if latest_state == "APPROVED":
            changed = handle_pr_approved_review(
                state,
                issue_number,
                assigned_reviewer,
                completion_source,
            )
            if changed:
                state_changed = True
                messages.append(
                    f"latest review by @{assigned_reviewer} is `APPROVED`; applied approval transitions"
                )
            else:
                messages.append(
                    f"latest review by @{assigned_reviewer} is `APPROVED`, but state already reflected it"
                )
        elif latest_state in {"COMMENTED", "CHANGES_REQUESTED"}:
            changed = update_reviewer_activity(state, issue_number, assigned_reviewer)
            if changed:
                state_changed = True
                messages.append(
                    f"latest review by @{assigned_reviewer} is `{latest_state}`; refreshed reviewer activity"
                )
            else:
                messages.append(
                    f"latest assigned-reviewer state is `{latest_state}` and no update was needed"
                )
        else:
            state_name = latest_state or "UNKNOWN"
            messages.append(
                f"latest review by @{assigned_reviewer} is `{state_name}` and no reconciliation transition applies"
            )

    review_data = ensure_review_entry(state, issue_number, create=True)
    if review_data and review_data.get("mandatory_approver_required"):
        escalation_opened_at = (
            parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at"))
            or parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        )
        triage_approval = find_triage_approval_after(reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")

    if state_changed:
        detail = "; ".join(messages) if messages else "applied state reconciliation transitions"
        return f"✅ Rectified PR #{issue_number}: {detail}.", True, True

    detail = "; ".join(messages) if messages else "no reconciliation transitions applied"
    return f"ℹ️ Rectify checked PR #{issue_number}: {detail}.", True, False


def handle_rectify_command(state: dict, issue_number: int, comment_author: str) -> tuple[str, bool, bool]:
    """Handle /rectify for the current issue/PR only.

    Permission model:
    - Allowed for the currently assigned reviewer.
    - Allowed for users with triage+ permissions.

    Returns (message, success, state_changed).
    """
    review_data = ensure_review_entry(state, issue_number)
    current_reviewer = review_data.get("current_reviewer") if review_data else None

    is_current_reviewer = (
        isinstance(current_reviewer, str)
        and current_reviewer.lower() == comment_author.lower()
    )

    has_triage = False
    if not is_current_reviewer:
        has_triage = check_user_permission(comment_author, "triage")

    if not is_current_reviewer and not has_triage:
        if current_reviewer:
            return (
                f"❌ Only the assigned reviewer (@{current_reviewer}) or a maintainer with triage+ "
                "permission can run `/rectify`.",
                False,
                False,
            )
        return (
            "❌ Only maintainers with triage+ permission can run `/rectify` when no assigned "
            "reviewer is tracked.",
            False,
            False,
        )

    return reconcile_active_review_entry(state, issue_number)


def check_overdue_reviews(state: dict) -> list[dict]:
    """
    Check all active reviews for overdue ones.
    
    Returns a list of overdue reviews with their status:
    [
        {
            "issue_number": 123,
            "reviewer": "username",
            "days_overdue": 5,
            "needs_warning": True,  # First warning needed
            "needs_transition": False,  # 28 days passed, transition needed
        },
        ...
    ]
    """
    if "active_reviews" not in state:
        return []
    
    now = datetime.now(timezone.utc)
    overdue = []
    
    for issue_key, review_data in state["active_reviews"].items():
        if not isinstance(review_data, dict):
            continue

        if review_data.get("review_completed_at"):
            continue
        
        current_reviewer = review_data.get("current_reviewer")
        if not current_reviewer:
            continue
        
        last_activity = review_data.get("last_reviewer_activity")
        if not last_activity:
            # No activity recorded, use assigned_at
            last_activity = review_data.get("assigned_at")
        if not last_activity:
            continue
        
        # Parse the timestamp
        try:
            last_activity_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        
        days_since_activity = (now - last_activity_dt).days
        
        if days_since_activity < REVIEW_DEADLINE_DAYS:
            continue  # Not overdue yet
        
        # Check if we've already sent a warning
        transition_warning_sent = review_data.get("transition_warning_sent")
        
        if transition_warning_sent:
            # Warning already sent - check if transition period has passed
            try:
                warning_dt = datetime.fromisoformat(transition_warning_sent.replace("Z", "+00:00"))
                days_since_warning = (now - warning_dt).days
                
                if days_since_warning >= TRANSITION_PERIOD_DAYS:
                    overdue.append({
                        "issue_number": int(issue_key),
                        "reviewer": current_reviewer,
                        "days_overdue": days_since_activity,
                        "days_since_warning": days_since_warning,
                        "needs_warning": False,
                        "needs_transition": True,
                    })
            except (ValueError, AttributeError):
                pass
        else:
            # First warning needed
            overdue.append({
                "issue_number": int(issue_key),
                "reviewer": current_reviewer,
                "days_overdue": days_since_activity - REVIEW_DEADLINE_DAYS,
                "days_since_warning": 0,
                "needs_warning": True,
                "needs_transition": False,
            })
    
    return overdue


def handle_overdue_review_warning(state: dict, issue_number: int, reviewer: str) -> bool:
    """
    Post a warning comment and record that we've warned the reviewer.
    
    Returns True if warning was posted, False otherwise.
    """
    issue_key = str(issue_number)
    
    if "active_reviews" not in state or issue_key not in state["active_reviews"]:
        return False
    
    review_data = state["active_reviews"][issue_key]
    if not isinstance(review_data, dict):
        return False
    
    # Post warning comment
    warning_message = f"""⚠️ **Review Reminder**

Hey @{reviewer}, it's been more than {REVIEW_DEADLINE_DAYS} days since you were assigned to review this.

**Please take one of the following actions:**

1. **Begin your review** - Post a comment with your feedback
2. **Pass the review** - Use `{BOT_MENTION} /pass [reason]` to assign the next reviewer
3. **Step away temporarily** - Use `{BOT_MENTION} /away YYYY-MM-DD [reason]` if you need time off

If no action is taken within {TRANSITION_PERIOD_DAYS} days, you may be transitioned from Producer to Observer status per our [contribution guidelines](CONTRIBUTING.md#review-deadlines).

_Life happens! If you're dealing with something, just let us know._"""
    
    post_comment(issue_number, warning_message)
    
    # Record that we've sent the warning
    now = datetime.now(timezone.utc).isoformat()
    review_data["transition_warning_sent"] = now
    
    print(f"Posted overdue warning for #{issue_number} to @{reviewer}")
    return True


def handle_transition_notice(state: dict, issue_number: int, reviewer: str) -> bool:
    """
    Post a notice that the transition period has ended.
    
    This does NOT automatically change their status - that requires manual intervention.
    Returns True if notice was posted, False otherwise.
    """
    # Post transition notice
    notice_message = f"""🔔 **Transition Period Ended**

@{reviewer}, the {TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

**The review will now be reassigned to the next person in the queue.**

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    
    post_comment(issue_number, notice_message)
    
    print(f"Posted transition notice for #{issue_number} to @{reviewer}")
    return True


def handle_issue_or_pr_opened(state: dict) -> bool:
    """
    Handle when an issue or PR is opened with a review label.

    Returns True if we took action, False otherwise.
    """
    assert_lock_held("handle_issue_or_pr_opened")

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

    # Check for review labels
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    print(f"ISSUE_LABELS env: {labels_json}")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        print("Failed to parse ISSUE_LABELS as JSON")
        labels = []

    if not any(label in REVIEW_LABELS for label in labels):
        print(
            f"Issue #{issue_number} does not have review labels {sorted(REVIEW_LABELS)} "
            f"(labels: {labels})"
        )
        return False

    # Get issue author to skip them
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    skip_set = {issue_author} if issue_author else set()

    # Get next reviewer
    reviewer = get_next_reviewer(state, skip_usernames=skip_set)

    if not reviewer:
        post_comment(issue_number,
                    f"⚠️ No reviewers available in the queue. "
                    f"Please use `{BOT_MENTION} /sync-members` to update the queue.")
        return False

    # Assign the reviewer.
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    assignment_attempt = request_reviewer_assignment(issue_number, reviewer)
    
    # Track the reviewer in our state (source of truth for pass command)
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    failure_comment = get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        post_comment(issue_number, failure_comment)

    # Post guidance comment
    if is_pr:
        if assignment_attempt.success:
            guidance = get_pr_guidance(reviewer, issue_author)
            post_comment(issue_number, guidance)
    else:
        if FLS_AUDIT_LABEL in labels:
            guidance = get_fls_audit_guidance(reviewer, issue_author)
        else:
            guidance = get_issue_guidance(reviewer, issue_author)
        post_comment(issue_number, guidance)

    return True


def handle_labeled_event(state: dict) -> bool:
    """
    Handle when an issue or PR is labeled with a review label.

    We already know from LABEL_NAME that the correct label was added,
    so we skip the label check that handle_issue_or_pr_opened does.
    """
    assert_lock_held("handle_labeled_event")

    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    label_name = os.environ.get("LABEL_NAME", "")
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"

    if label_name == "sign-off: create pr":
        if is_pr:
            print("Sign-off label applied to PR; ignoring")
            return False
        review_data = ensure_review_entry(state, issue_number)
        reviewer = None
        if review_data:
            reviewer = review_data.get("current_reviewer")
        return mark_review_complete(
            state,
            issue_number,
            reviewer,
            "issue_label: sign-off: create pr",
        )

    if label_name not in REVIEW_LABELS:
        print(f"Label '{label_name}' is not a review label, skipping")
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
                    f"Please use `{BOT_MENTION} /sync-members` to update the queue.")
        return False

    # Assign the reviewer.
    assignment_attempt = request_reviewer_assignment(issue_number, reviewer)
    
    # Track the reviewer in our state
    set_current_reviewer(state, issue_number, reviewer)

    # Record the assignment
    record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")

    failure_comment = get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        post_comment(issue_number, failure_comment)

    # Post guidance comment
    if is_pr:
        if assignment_attempt.success:
            guidance = get_pr_guidance(reviewer, issue_author)
            post_comment(issue_number, guidance)
    else:
        if label_name == FLS_AUDIT_LABEL:
            guidance = get_fls_audit_guidance(reviewer, issue_author)
        else:
            guidance = get_issue_guidance(reviewer, issue_author)
        post_comment(issue_number, guidance)

    return True


def handle_pull_request_review_event(state: dict) -> bool:
    """Handle submitted PR reviews for activity and completion tracking."""
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        print("No issue number found")
        return False

    review_state = os.environ.get("REVIEW_STATE", "").strip().upper()
    review_author = os.environ.get("REVIEW_AUTHOR", "").strip()
    if not review_state or not review_author:
        print("Missing review context")
        return False

    is_cross_repo = os.environ.get("PR_IS_CROSS_REPOSITORY", "false").lower() == "true"
    if is_cross_repo:
        print(
            "Deferring cross-repo pull_request_review reconciliation for "
            f"#{issue_number}: this event may have read-only permissions. "
            "A trusted workflow_run reconcile will persist state after this run succeeds. "
            "If needed, use `@guidelines-bot /rectify` as manual fallback."
        )
        return False

    assert_lock_held("handle_pull_request_review_event")

    review_data = ensure_review_entry(state, issue_number)
    if review_data is None:
        print(f"No active review entry for #{issue_number}")
        return False

    current_reviewer = review_data.get("current_reviewer")
    if review_state == "APPROVED":
        return handle_pr_approved_review(
            state,
            issue_number,
            review_author,
            "pull_request_review",
        )

    if review_state in {"COMMENTED", "CHANGES_REQUESTED"}:
        if not current_reviewer or current_reviewer.lower() != review_author.lower():
            print(
                f"Ignoring review from @{review_author} on #{issue_number}; "
                f"current reviewer is @{current_reviewer}"
            )
            return False
        return update_reviewer_activity(state, issue_number, review_author)

    print(f"Ignoring review state '{review_state}' for #{issue_number}")
    return False


def handle_workflow_run_event(state: dict) -> bool:
    """Handle trusted second-hop workflow_run reconciliation."""
    assert_lock_held("handle_workflow_run_event")

    workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
    if workflow_run_event != "pull_request_review":
        observed = workflow_run_event or "<missing>"
        print(
            "Ignoring workflow_run reconcile event with unsupported source event: "
            f"{observed}"
        )
        return False

    issue_number = resolve_workflow_run_pr_number()

    message, success, state_changed = reconcile_active_review_entry(
        state,
        issue_number,
        require_pull_request_context=False,
        completion_source="workflow_run:pull_request_review",
    )
    print(message)

    if not success:
        raise RuntimeError(
            f"Workflow_run reconcile failed for pull request #{issue_number}: {message}"
        )

    if state_changed and not post_comment(issue_number, message):
        print(
            "WARNING: Workflow_run reconcile changed state but failed to post "
            f"comment on pull request #{issue_number}.",
            file=sys.stderr,
        )

    return state_changed


def handle_closed_event(state: dict) -> bool:
    """
    Handle when an issue or PR is closed.
    
    Cleans up the active_reviews entry to prevent state from growing indefinitely.

    Returns True if we modified state, False otherwise.
    """
    assert_lock_held("handle_closed_event")

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
    Handle a comment event - check for bot commands and track reviewer activity.

    Returns True if we took action, False otherwise.
    """
    assert_lock_held("handle_comment_event")

    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_id = os.environ.get("COMMENT_ID", "")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))

    if not comment_body or not issue_number:
        return False

    # Check if comment author is the current reviewer - if so, update their activity
    # This resets the 14-day deadline clock
    activity_updated = update_reviewer_activity(state, issue_number, comment_author)
    
    # Parse for bot command
    sanitized_body = strip_code_blocks(comment_body)
    parsed = parse_command(sanitized_body)
    if not parsed:
        # No bot command, but we may have updated activity
        return activity_updated

    command, args = parsed
    print(f"Parsed command: {command}, args: {args}")

    response = ""
    success = False
    state_changed = False

    if command == "_multiple_commands":
        response = ("⚠️ Multiple bot commands in one comment are ignored. "
                    "Please post a single command per comment. "
                    f"For a list of commands, use `{BOT_MENTION} /commands`.")
        success = False
    # Handle each command
    elif command == "pass":
        reason = " ".join(args) if args else None
        response, success = handle_pass_command(state, issue_number, comment_author, reason)
        state_changed = success

    elif command == "away":
        if not args:
            response = (f"❌ Missing date. Usage: `{BOT_MENTION} /away YYYY-MM-DD [reason]`")
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
            response = (f"❌ Missing label. Usage: `{BOT_MENTION} /label +label-name` or "
                       f"`{BOT_MENTION} /label -label-name`")
            success = False
        else:
            # Rejoin all args to handle labels with spaces
            # Then parse for +label and -label patterns
            full_arg = " ".join(args)
            response, success = handle_label_command(issue_number, full_arg)

    elif command == "accept-no-fls-changes":
        response, success = handle_accept_no_fls_changes_command(issue_number, comment_author)

    elif command == "sync-members":
        response, success = handle_sync_members_command(state)
        state_changed = success

    elif command == "queue":
        response, success = handle_queue_command(state)

    elif command == "commands":
        response, success = handle_commands_command()

    elif command == "claim":
        response, success = handle_claim_command(state, issue_number, comment_author)
        state_changed = success

    elif command == "release":
        # Pass args to handle_release_command for @username parsing
        response, success = handle_release_command(state, issue_number, comment_author, args)
        state_changed = success

    elif command == "rectify":
        response, success, state_changed = handle_rectify_command(
            state,
            issue_number,
            comment_author,
        )

    elif command == "r?-user":
        # Handle "/r? @username" - assign specific user
        username = args[0] if args else ""
        response, success = handle_assign_command(state, issue_number, username)
        state_changed = success

    elif command == "assign-from-queue":
        # Handle "/r? producers" - assign next from round-robin queue
        response, success = handle_assign_from_queue_command(state, issue_number)
        state_changed = success

    elif command == "r?":
        # Handle "/r?" with no target - show usage error
        response = (f"❌ Missing target. Usage:\n"
                   f"- `{BOT_MENTION} /r? @username` - Assign a specific reviewer\n"
                   f"- `{BOT_MENTION} /r? producers` - Assign next reviewer from queue")
        success = False

    elif command == "_malformed_known":
        # User typed a known command but forgot the / prefix
        attempted = args[0] if args else "command"
        response = (f"⚠️ Did you mean `{BOT_MENTION} /{attempted}`?\n\n"
                   f"Commands require a `/` prefix.")
        success = False

    elif command == "_malformed_unknown":
        # User typed something after @guidelines-bot but it's not a known command
        attempted = args[0] if args else ""
        response = (f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\n"
                   f"Try `{BOT_MENTION} /commands` to see available commands.")
        success = False

    else:
        response = (f"❌ Unknown command: `/{command}`\n\n"
                   f"Available commands:\n{get_commands_help()}")
        success = False

    # React to the command comment
    if comment_id and command != "_multiple_commands":
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

    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False

    assert_lock_held("handle_manual_dispatch")

    if action == "sync-members":
        state, changes = sync_members_with_queue(state)
        if changes:
            print(f"Sync changes: {changes}")
        return True

    elif action == "check-overdue":
        # Manually trigger the overdue review check
        return handle_scheduled_check(state)

    return False


def handle_scheduled_check(state: dict) -> bool:
    """
    Handle the scheduled (nightly) check for overdue reviews.
    
    This function:
    1. Checks all active reviews for overdue ones
    2. Posts warnings for reviews that are 14+ days overdue
    3. Posts transition notices and reassigns for 28+ days overdue

    Returns True if any action was taken, False otherwise.
    """
    assert_lock_held("handle_scheduled_check")

    print("Running scheduled check for overdue reviews...")
    
    overdue_reviews = check_overdue_reviews(state)
    
    if not overdue_reviews:
        print("No overdue reviews found.")
        return False
    
    print(f"Found {len(overdue_reviews)} overdue review(s)")
    
    state_changed = False
    
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        
        if review["needs_warning"]:
            # First warning - 14 days overdue
            print(f"Sending warning for #{issue_number} to @{reviewer} "
                  f"({review['days_overdue']} days overdue)")
            if handle_overdue_review_warning(state, issue_number, reviewer):
                state_changed = True
        
        elif review["needs_transition"]:
            # Transition period ended - 28 days total
            print(f"Transition period ended for #{issue_number}, @{reviewer} "
                  f"({review['days_since_warning']} days since warning)")
            
            # Post the transition notice
            handle_transition_notice(state, issue_number, reviewer)
            
            # Reassign to next in queue
            issue_key = str(issue_number)
            review_data = state["active_reviews"].get(issue_key, {})
            skipped = review_data.get("skipped", [])
            
            # Get issue author to skip
            # Note: We don't have easy access to issue author here, so we'll skip the current reviewer
            skip_set = set(skipped) | {reviewer}
            
            next_reviewer = get_next_reviewer(state, skip_usernames=skip_set)
            
            if next_reviewer:
                # Unassign old reviewer
                unassign_reviewer(issue_number, reviewer)
                
                # Assign new reviewer
                assignment_attempt = request_reviewer_assignment(issue_number, next_reviewer)
                set_current_reviewer(state, issue_number, next_reviewer)
                
                # Track the skip
                if issue_key in state["active_reviews"]:
                    if reviewer not in state["active_reviews"][issue_key].get("skipped", []):
                        state["active_reviews"][issue_key]["skipped"].append(reviewer)
                
                # Post assignment comment (assume issue since we don't track type here)
                failure_comment = get_assignment_failure_comment(next_reviewer, assignment_attempt)
                if failure_comment:
                    post_comment(issue_number, failure_comment)

                guidance = get_issue_guidance(next_reviewer, "the contributor")
                post_comment(issue_number, guidance)
                
                # Record assignment
                record_assignment(state, next_reviewer, issue_number, "issue")
                
                print(f"Reassigned #{issue_number} from @{reviewer} to @{next_reviewer}")
            else:
                print(f"No available reviewers to reassign #{issue_number}")
            
            state_changed = True
    
    return state_changed


# ==============================================================================
# Main
# ==============================================================================


def classify_event_intent(event_name: str, event_action: str) -> str:
    """Classify whether a run can mutate reviewer-bot state."""
    if event_name in {"issues", "pull_request_target"}:
        if event_action in {"opened", "labeled", "closed"}:
            return EVENT_INTENT_MUTATING
        return EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "issue_comment":
        if event_action == "created":
            return EVENT_INTENT_MUTATING
        return EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "pull_request_review":
        if event_action != "submitted":
            return EVENT_INTENT_NON_MUTATING_READONLY
        is_cross_repo = os.environ.get("PR_IS_CROSS_REPOSITORY", "false").lower() == "true"
        if is_cross_repo:
            return EVENT_INTENT_NON_MUTATING_DEFER
        return EVENT_INTENT_MUTATING

    if event_name == "workflow_run":
        if event_action != "completed":
            return EVENT_INTENT_NON_MUTATING_READONLY
        workflow_run_event = os.environ.get("WORKFLOW_RUN_EVENT", "").strip()
        if workflow_run_event == "pull_request_review":
            return EVENT_INTENT_MUTATING
        return EVENT_INTENT_NON_MUTATING_READONLY

    if event_name == "workflow_dispatch":
        action = os.environ.get("MANUAL_ACTION", "").strip()
        if action == "show-state":
            return EVENT_INTENT_NON_MUTATING_READONLY
        return EVENT_INTENT_MUTATING

    if event_name == "schedule":
        return EVENT_INTENT_MUTATING

    return EVENT_INTENT_NON_MUTATING_READONLY


def event_requires_lease_lock(event_name: str, event_action: str) -> bool:
    """Backwards-compatible helper for tests and call sites."""
    return classify_event_intent(event_name, event_action) == EVENT_INTENT_MUTATING


def main():
    """Main entry point for the reviewer bot."""
    event_name = os.environ.get("EVENT_NAME", "")
    event_action = os.environ.get("EVENT_ACTION", "")

    event_intent = classify_event_intent(event_name, event_action)
    lock_required = event_intent == EVENT_INTENT_MUTATING
    print(
        f"Event: {event_name}, Action: {event_action}, Intent: {event_intent}, "
        f"Lock Required: {lock_required}"
    )

    lock_acquired = False
    release_failed = False
    exit_code = 0

    state_changed = False
    sync_changes: list[str] = []
    restored: list[str] = []

    try:
        if lock_required:
            acquire_state_issue_lease_lock()
            lock_acquired = True

        # Load current state
        state = load_state()

        if lock_required:
            # Process any expired pass-until entries
            state, restored = process_pass_until_expirations(state)
            if restored:
                print(f"Restored from pass-until: {restored}")

            # Always sync members on mutating paths
            state, sync_changes = sync_members_with_queue(state)
            if sync_changes:
                print(f"Members sync changes: {sync_changes}")

        # Handle the event
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

        elif event_name == "pull_request_review":
            if event_action == "submitted":
                state_changed = handle_pull_request_review_event(state)

        elif event_name == "issue_comment":
            if event_action == "created":
                state_changed = handle_comment_event(state)

        elif event_name == "workflow_dispatch":
            state_changed = handle_manual_dispatch(state)

        elif event_name == "schedule":
            # Nightly check for overdue reviews
            state_changed = handle_scheduled_check(state)

        elif event_name == "workflow_run":
            if event_action == "completed":
                if os.environ.get("WORKFLOW_RUN_EVENT", "").strip() == "pull_request_review":
                    state_changed = handle_workflow_run_event(state)
                else:
                    print(
                        "Ignoring workflow_run event with unsupported source event: "
                        f"{os.environ.get('WORKFLOW_RUN_EVENT', '').strip() or '<missing>'}"
                    )

        # Save state if changed (or if we synced members/pass-until)
        if state_changed or sync_changes or restored:
            if not lock_acquired:
                raise RuntimeError(
                    "State mutation reached save path without lease lock. "
                    "Acquire lock before mutating state."
                )

            print("State updates detected; attempting to persist reviewer-bot state.")
            if not save_state(state):
                raise RuntimeError(
                    "State updates were computed but could not be persisted. "
                    "Failing this run to avoid silent success."
                )

            with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
                f.write("state_changed=true\n")
        else:
            with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
                f.write("state_changed=false\n")

    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = 1
    except Exception as exc:  # pragma: no cover - defensive hard-fail path
        print(f"ERROR: Unexpected reviewer-bot failure: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if lock_acquired:
            if not release_state_issue_lease_lock():
                release_failed = True

    if release_failed:
        print(
            "ERROR: Failed to release reviewer-bot lease lock after processing event.",
            file=sys.stderr,
        )
        exit_code = 1

    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
