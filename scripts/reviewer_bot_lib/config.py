"""Reviewer-bot configuration constants and small shared types."""

import os
from dataclasses import dataclass
from typing import Any

BOT_NAME = "guidelines-bot"
BOT_MENTION = f"@{BOT_NAME}"
CODING_GUIDELINE_LABEL = "coding guideline"
FLS_AUDIT_LABEL = "fls-audit"
REVIEW_LABELS = {CODING_GUIDELINE_LABEL, FLS_AUDIT_LABEL}
STATE_ISSUE_NUMBER = int(os.environ.get("STATE_ISSUE_NUMBER", "0"))
MEMBERS_URL = (
    "https://raw.githubusercontent.com/rustfoundation/"
    "safety-critical-rust-consortium/main/subcommittee/coding-guidelines/members.md"
)
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
STATE_READ_RETRY_LIMIT = int(os.environ.get("REVIEWER_BOT_STATE_READ_RETRY_LIMIT", "4"))
STATE_READ_RETRY_BASE_SECONDS = float(
    os.environ.get("REVIEWER_BOT_STATE_READ_RETRY_SECONDS", "1")
)
LOCK_RENEWAL_WINDOW_SECONDS = int(
    os.environ.get("REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS", "60")
)
LOCK_REF_NAME = os.environ.get("REVIEWER_BOT_LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
LOCK_REF_BOOTSTRAP_BRANCH = os.environ.get("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", "main")
LOCK_COMMIT_MARKER = "reviewer-bot-lock-v1"

EVENT_INTENT_MUTATING = "mutating"
EVENT_INTENT_NON_MUTATING_DEFER = "non_mutating_defer"
EVENT_INTENT_NON_MUTATING_READONLY = "non_mutating_readonly"

STATE_SCHEMA_VERSION = 18
FRESHNESS_RUNTIME_EPOCH_LEGACY = "legacy_v14"
FRESHNESS_RUNTIME_EPOCH_V18 = "freshness_v15"
REVIEW_FRESHNESS_RUNBOOK_PATH = "docs/reviewer-bot-review-freshness-operator-runbook.md"
AUTHOR_ASSOCIATION_TRUST_ALLOWLIST = {"OWNER", "MEMBER", "COLLABORATOR"}
DEFERRED_ARTIFACT_RETENTION_DAYS = 7
DEFERRED_MISSING_RUN_WINDOW_SECONDS = 24 * 60 * 60
DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS = 7 * 24 * 60 * 60
DEFERRED_DISCOVERY_OVERLAP_SECONDS = 60 * 60

MANDATORY_TRIAGE_APPROVER_LABEL = "triage approver required"
STATUS_AWAITING_REVIEWER_RESPONSE_LABEL = "status: awaiting reviewer response"
STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL = "status: awaiting contributor response"
STATUS_AWAITING_WRITE_APPROVAL_LABEL = "status: awaiting write approval"
STATUS_AWAITING_REVIEW_COMPLETION_LABEL = STATUS_AWAITING_REVIEWER_RESPONSE_LABEL
STATUS_LABELS = {
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL,
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
    STATUS_AWAITING_WRITE_APPROVAL_LABEL,
}
STATUS_LABEL_CONFIG = {
    STATUS_AWAITING_REVIEWER_RESPONSE_LABEL: {
        "color": "fbca04",
        "description": "Reviewer-bot is waiting on reviewer freshness or current-head review",
    },
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL: {
        "color": "0e8a16",
        "description": "Reviewer-bot is waiting on contributor follow-up or completion",
    },
    STATUS_AWAITING_WRITE_APPROVAL_LABEL: {
        "color": "1d76db",
        "description": "Assigned review is complete but no visible write+ approval is present",
    },
    MANDATORY_TRIAGE_APPROVER_LABEL: {
        "color": "d73a4a",
        "description": "Indicates triage+ approval is required before merge queue",
    },
}
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

REVIEW_DEADLINE_DAYS = 14
TRANSITION_PERIOD_DAYS = 14

COMMANDS = {
    "pass": "Pass this review to next in queue",
    "away": "Step away from queue until date (YYYY-MM-DD)",
    "release": "Release assignment (yours, or @username with triage+ permission)",
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
    """Generate help text from the command registry."""
    return "\n".join(f"- `{BOT_MENTION} /{cmd}` - {desc}" for cmd, desc in COMMANDS.items())


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
