"""Reviewer-bot configuration constants and small shared types."""

from dataclasses import dataclass, field
from typing import Any

BOT_NAME = "guidelines-bot"
BOT_MENTION = f"@{BOT_NAME}"
CODING_GUIDELINE_LABEL = "coding guideline"
FLS_AUDIT_LABEL = "fls-audit"
REVIEW_LABELS = {CODING_GUIDELINE_LABEL, FLS_AUDIT_LABEL}
STATE_ISSUE_NUMBER_ENV = "STATE_ISSUE_NUMBER"
STATE_ISSUE_NUMBER = 0
MEMBERS_URL = (
    "https://raw.githubusercontent.com/rustfoundation/"
    "safety-critical-rust-consortium/main/subcommittee/coding-guidelines/members.md"
)
MAX_RECENT_ASSIGNMENTS = 20

STATE_BLOCK_START_MARKER = "<!-- REVIEWER_BOT_STATE_START -->"
STATE_BLOCK_END_MARKER = "<!-- REVIEWER_BOT_STATE_END -->"
LOCK_BLOCK_START_MARKER = "<!-- REVIEWER_BOT_LOCK_START -->"
LOCK_BLOCK_END_MARKER = "<!-- REVIEWER_BOT_LOCK_END -->"
TRANSITION_NOTICE_MARKER_PREFIX = "reviewer-bot:transition-notice:v1"
TRANSITION_WARNING_MARKER_PREFIX = "reviewer-bot:transition-warning:v1"

LOCK_SCHEMA_VERSION = 1
LOCK_LEASE_TTL_SECONDS_ENV = "REVIEWER_BOT_LOCK_TTL_SECONDS"
LOCK_RETRY_BASE_SECONDS_ENV = "REVIEWER_BOT_LOCK_RETRY_SECONDS"
LOCK_MAX_WAIT_SECONDS_ENV = "REVIEWER_BOT_LOCK_MAX_WAIT_SECONDS"
LOCK_API_RETRY_LIMIT_ENV = "REVIEWER_BOT_LOCK_API_RETRY_LIMIT"
STATE_READ_RETRY_LIMIT_ENV = "REVIEWER_BOT_STATE_READ_RETRY_LIMIT"
STATE_READ_RETRY_BASE_SECONDS_ENV = "REVIEWER_BOT_STATE_READ_RETRY_SECONDS"
LOCK_RENEWAL_WINDOW_SECONDS_ENV = "REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS"
LOCK_REF_NAME_ENV = "REVIEWER_BOT_LOCK_REF_NAME"
LOCK_REF_BOOTSTRAP_BRANCH_ENV = "REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH"
LOCK_LEASE_TTL_SECONDS = 300
LOCK_RETRY_BASE_SECONDS = 2.0
LOCK_MAX_WAIT_SECONDS = 1200
LOCK_API_RETRY_LIMIT = 5
STATE_READ_RETRY_LIMIT = 4
STATE_READ_RETRY_BASE_SECONDS = 1.0
LOCK_RENEWAL_WINDOW_SECONDS = 60
LOCK_REF_NAME = "heads/reviewer-bot-state-lock"
LOCK_REF_BOOTSTRAP_BRANCH = "main"
LOCK_COMMIT_MARKER = "reviewer-bot-lock-v1"

EVENT_INTENT_MUTATING = "mutating"
EVENT_INTENT_NON_MUTATING_DEFER = "non_mutating_defer"
EVENT_INTENT_NON_MUTATING_READONLY = "non_mutating_readonly"

STATE_SCHEMA_VERSION = 19
FRESHNESS_RUNTIME_EPOCH_LEGACY = "legacy_v14"
FRESHNESS_RUNTIME_EPOCH_V18 = "freshness_v15"
STATUS_PROJECTION_EPOCH = "status_projection_v2"
REVIEWER_BOARD_ENABLED_ENV = "REVIEWER_BOARD_ENABLED"
REVIEWER_BOARD_TOKEN_ENV = "REVIEWER_BOARD_TOKEN"
REVIEWER_BOARD_ORG = "rustfoundation"
REVIEWER_BOARD_PROJECT_NUMBER = 1
REVIEWER_BOARD_FIELD_REVIEW_STATE = "Review State"
REVIEWER_BOARD_FIELD_REVIEWER = "Reviewer"
REVIEWER_BOARD_FIELD_ASSIGNED_AT = "Assigned At"
REVIEWER_BOARD_FIELD_WAITING_SINCE = "Waiting Since"
REVIEWER_BOARD_FIELD_NEEDS_ATTENTION = "Needs Attention"
REVIEWER_BOARD_OPTION_AWAITING_REVIEWER = "Awaiting Reviewer"
REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR = "Awaiting Contributor"
REVIEWER_BOARD_OPTION_AWAITING_WRITE_APPROVAL = "Awaiting Write Approval"
REVIEWER_BOARD_OPTION_DONE = "Done"
REVIEWER_BOARD_OPTION_UNASSIGNED = "Unassigned"
REVIEWER_BOARD_OPTION_ATTENTION_NO = "No"
REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT = "Warning Sent"
REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT = "Transition Notice Sent"
REVIEWER_BOARD_OPTION_ATTENTION_TRIAGE_APPROVAL_REQUIRED = "Triage Approval Required"
REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED = "Projection Repair Required"
REVIEW_FRESHNESS_RUNBOOK_PATH = "docs/reviewer-bot-review-freshness-operator-runbook.md"
AUTHOR_ASSOCIATION_TRUST_ALLOWLIST = {"OWNER", "MEMBER", "COLLABORATOR"}
DEFERRED_ARTIFACT_RETENTION_DAYS = 7
DEFERRED_MISSING_RUN_WINDOW_SECONDS = 24 * 60 * 60
DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS = 7 * 24 * 60 * 60
DEFERRED_DISCOVERY_OVERLAP_SECONDS = 60 * 60

REVIEWER_BOARD_PROJECT_MANIFEST = {
    REVIEWER_BOARD_FIELD_REVIEW_STATE: {
        "type": "single_select",
        "required": True,
        "options": (
            REVIEWER_BOARD_OPTION_AWAITING_REVIEWER,
            REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR,
            REVIEWER_BOARD_OPTION_AWAITING_WRITE_APPROVAL,
            REVIEWER_BOARD_OPTION_DONE,
            REVIEWER_BOARD_OPTION_UNASSIGNED,
        ),
    },
    REVIEWER_BOARD_FIELD_REVIEWER: {
        "type": "text",
        "required": True,
        "options": (),
    },
    REVIEWER_BOARD_FIELD_ASSIGNED_AT: {
        "type": "date",
        "required": True,
        "options": (),
    },
    REVIEWER_BOARD_FIELD_WAITING_SINCE: {
        "type": "date",
        "required": True,
        "options": (),
    },
    REVIEWER_BOARD_FIELD_NEEDS_ATTENTION: {
        "type": "single_select",
        "required": True,
        "options": (
            REVIEWER_BOARD_OPTION_ATTENTION_NO,
            REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT,
            REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT,
            REVIEWER_BOARD_OPTION_ATTENTION_TRIAGE_APPROVAL_REQUIRED,
            REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED,
        ),
    },
}

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
    "feedback": "Record that reviewer feedback is ready for contributor follow-up",
    "release": "Release your current reviewer assignment",
    "rectify": "Reconcile this issue/PR's review state from GitHub",
    "claim": "Claim this review for yourself",
    "r?": "Assign a reviewer (@username or 'producers')",
    "done": "Mark a tracked non-PR issue review complete",
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
    status_code: int | None
    payload: Any
    headers: dict[str, str]
    text: str
    ok: bool
    failure_kind: str | None = None
    retry_attempts: int = 0
    transport_error: str | None = None


@dataclass
class AssignmentAttempt:
    success: bool
    status_code: int | None
    exhausted_retryable_failure: bool = False
    failure_kind: str | None = None
    retry_attempts: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    transport_error: str | None = None


@dataclass(frozen=True)
class MemberFetchResult:
    ok: bool
    producers: list[dict[str, str]]
    failure_kind: str | None = None


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
