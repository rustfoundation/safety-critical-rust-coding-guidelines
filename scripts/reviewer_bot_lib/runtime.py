"""Explicit runtime service composition for reviewer-bot orchestration."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
    BOT_MENTION,
    BOT_NAME,
    COMMANDS,
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS,
    DEFERRED_DISCOVERY_OVERLAP_SECONDS,
    EVENT_INTENT_MUTATING,
    EVENT_INTENT_NON_MUTATING_DEFER,
    EVENT_INTENT_NON_MUTATING_READONLY,
    FLS_AUDIT_LABEL,
    LOCK_API_RETRY_LIMIT,
    LOCK_LEASE_TTL_SECONDS,
    LOCK_MAX_WAIT_SECONDS,
    LOCK_REF_BOOTSTRAP_BRANCH,
    LOCK_REF_NAME,
    LOCK_RENEWAL_WINDOW_SECONDS,
    LOCK_RETRY_BASE_SECONDS,
    REVIEW_DEADLINE_DAYS,
    REVIEW_FRESHNESS_RUNBOOK_PATH,
    REVIEW_LABELS,
    REVIEWER_REQUEST_422_TEMPLATE,
    STATE_ISSUE_NUMBER,
    STATUS_PROJECTION_EPOCH,
    TRANSITION_PERIOD_DAYS,
)


class _EnvConfig:
    def get(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def set(self, name: str, value: Any) -> None:
        os.environ[name] = str(value)


class _FileOutputSink:
    def __init__(self, config: _EnvConfig):
        self._config = config

    def write(self, name: str, value: str) -> None:
        output_path = self._config.get("GITHUB_OUTPUT", "/dev/null")
        with open(output_path, "a", encoding="utf-8") as output_file:
            output_file.write(f"{name}={value}\n")


class _JsonDeferredPayloadLoader:
    def __init__(self, config: _EnvConfig):
        self._config = config

    def load(self) -> dict:
        path = self._config.get("DEFERRED_CONTEXT_PATH", "").strip()
        if not path:
            raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
        with open(Path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RuntimeError("Deferred context payload must be a JSON object")
        return payload


class _TouchTracker:
    def __init__(self):
        self._touched: set[int] = set()

    def collect(self, issue_number: int | None) -> None:
        if isinstance(issue_number, int) and issue_number > 0:
            self._touched.add(issue_number)

    def drain(self) -> list[int]:
        touched = sorted(self._touched)
        self._touched.clear()
        return touched


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SystemSleeper:
    def __init__(self, time_module: Any):
        self._time = time_module

    def sleep(self, seconds: float) -> None:
        self._time.sleep(seconds)


class RandomJitterSource:
    def __init__(self, random_module: Any):
        self._random = random_module

    def uniform(self, lower: float, upper: float) -> float:
        return self._random.uniform(lower, upper)


class Uuid4Source:
    def uuid4_hex(self) -> str:
        return uuid.uuid4().hex


class StdErrLogger:
    def __init__(self, sys_module: Any):
        self._sys = sys_module

    def event(self, level: str, message: str, **fields: Any) -> None:
        rendered_fields = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        suffix = f" {rendered_fields}" if rendered_fields else ""
        self._sys.stderr.write(f"[{level}] {message}{suffix}\n")


class ReviewerBotRuntime:
    """Runtime object built from explicit services and named adapters."""

    BOT_NAME = BOT_NAME
    BOT_MENTION = BOT_MENTION
    COMMANDS = COMMANDS
    FLS_AUDIT_LABEL = FLS_AUDIT_LABEL
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST = AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
    REVIEWER_REQUEST_422_TEMPLATE = REVIEWER_REQUEST_422_TEMPLATE
    REVIEW_FRESHNESS_RUNBOOK_PATH = REVIEW_FRESHNESS_RUNBOOK_PATH
    REVIEW_DEADLINE_DAYS = REVIEW_DEADLINE_DAYS
    TRANSITION_PERIOD_DAYS = TRANSITION_PERIOD_DAYS
    REVIEW_LABELS = REVIEW_LABELS
    DEFERRED_DISCOVERY_OVERLAP_SECONDS = DEFERRED_DISCOVERY_OVERLAP_SECONDS
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS = DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS
    EVENT_INTENT_MUTATING = EVENT_INTENT_MUTATING
    EVENT_INTENT_NON_MUTATING_DEFER = EVENT_INTENT_NON_MUTATING_DEFER
    EVENT_INTENT_NON_MUTATING_READONLY = EVENT_INTENT_NON_MUTATING_READONLY
    STATUS_PROJECTION_EPOCH = STATUS_PROJECTION_EPOCH
    datetime = datetime
    timezone = timezone

    def __init__(
        self,
        *,
        requests: Any,
        sys: Any,
        random: Any,
        time: Any,
        config: Any | None = None,
        outputs: Any | None = None,
        deferred_payloads: Any | None = None,
        clock: Any | None = None,
        sleeper: Any | None = None,
        jitter: Any | None = None,
        uuid_source: Any | None = None,
        logger: Any | None = None,
        state_store: Any,
        github: Any,
        locks: Any,
        handlers: Any,
        adapters: Any,
        touch_tracker: Any | None = None,
        active_lease_context: Any | None = None,
    ):
        self.requests = requests
        self.sys = sys
        self.random = random
        self.time = time
        self.config = config or _EnvConfig()
        self.outputs = outputs or _FileOutputSink(self.config)
        self.deferred_payloads = deferred_payloads or _JsonDeferredPayloadLoader(self.config)
        self.clock = clock or SystemClock()
        self.sleeper = sleeper or SystemSleeper(time)
        self.jitter = jitter or RandomJitterSource(random)
        self.uuid_source = uuid_source or Uuid4Source()
        self.logger = logger or StdErrLogger(sys)
        self.state_store = state_store
        self.github = github
        self.locks = locks
        self.handlers = handlers
        self.adapters = adapters
        self.touch_tracker = touch_tracker or _TouchTracker()
        self.ACTIVE_LEASE_CONTEXT = active_lease_context

    def get_config_value(self, name: str, default: str = "") -> str:
        return self.config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self.config.set(name, value)

    def state_issue_number(self) -> int:
        return int(self.get_config_value("STATE_ISSUE_NUMBER", str(STATE_ISSUE_NUMBER or 0)) or 0)

    def lock_api_retry_limit(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_API_RETRY_LIMIT", str(LOCK_API_RETRY_LIMIT)) or 0)

    def lock_retry_base_seconds(self) -> float:
        return float(self.get_config_value("REVIEWER_BOT_LOCK_RETRY_SECONDS", str(LOCK_RETRY_BASE_SECONDS)) or 0.0)

    def lock_max_wait_seconds(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_MAX_WAIT_SECONDS", str(LOCK_MAX_WAIT_SECONDS)) or 0)

    def lock_lease_ttl_seconds(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_TTL_SECONDS", str(LOCK_LEASE_TTL_SECONDS)) or 0)

    def lock_renewal_window_seconds(self) -> int:
        return int(
            self.get_config_value(
                "REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS",
                str(LOCK_RENEWAL_WINDOW_SECONDS),
            )
            or 0
        )

    def lock_ref_name(self) -> str:
        return self.get_config_value("REVIEWER_BOT_LOCK_REF_NAME", LOCK_REF_NAME)

    def lock_ref_bootstrap_branch(self) -> str:
        return self.get_config_value("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", LOCK_REF_BOOTSTRAP_BRANCH)

    def write_output(self, name: str, value: str) -> None:
        self.outputs.write(name, value)

    def load_deferred_payload(self) -> dict:
        return self.deferred_payloads.load()

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self.state_store.load_state(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self.state_store.save_state(state)

    def github_api_request(self, *args, **kwargs):
        return self.github.github_api_request(*args, **kwargs)

    def github_api(self, *args, **kwargs):
        return self.github.github_api(*args, **kwargs)

    def collect_touched_item(self, issue_number: int | None) -> None:
        self.touch_tracker.collect(issue_number)

    def drain_touched_items(self) -> list[int]:
        return self.touch_tracker.drain()

    def handle_issue_or_pr_opened(self, state: dict) -> bool:
        return self.handlers.handle_issue_or_pr_opened(state)

    def handle_labeled_event(self, state: dict) -> bool:
        return self.handlers.handle_labeled_event(state)

    def handle_issue_edited_event(self, state: dict) -> bool:
        return self.handlers.handle_issue_edited_event(state)

    def handle_closed_event(self, state: dict) -> bool:
        return self.handlers.handle_closed_event(state)

    def handle_pull_request_target_synchronize(self, state: dict) -> bool:
        return self.handlers.handle_pull_request_target_synchronize(state)

    def handle_pull_request_review_event(self, state: dict) -> bool:
        return self.handlers.handle_pull_request_review_event(state)

    def handle_comment_event(self, state: dict) -> bool:
        return self.handlers.handle_comment_event(state)

    def handle_manual_dispatch(self, state: dict) -> bool:
        return self.handlers.handle_manual_dispatch(state)

    def handle_scheduled_check(self, state: dict) -> bool:
        return self.handlers.handle_scheduled_check(state)

    def handle_workflow_run_event(self, state: dict) -> bool:
        return self.handlers.handle_workflow_run_event(state)

    def assert_lock_held(self, context: str) -> None:
        return self.adapters.assert_lock_held(context)

    def get_github_token(self) -> str:
        return self.adapters.get_github_token()

    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str:
        return self.adapters.get_github_graphql_token(prefer_board_token=prefer_board_token)

    def github_graphql(self, query: str, variables=None, *, token=None):
        return self.adapters.github_graphql(query, variables, token=token)

    def post_comment(self, issue_number: int, body: str) -> bool:
        return self.adapters.post_comment(issue_number, body)

    def get_repo_labels(self):
        return self.adapters.get_repo_labels()

    def add_label(self, issue_number: int, label: str) -> bool:
        return self.adapters.add_label(issue_number, label)

    def remove_label(self, issue_number: int, label: str) -> bool:
        return self.adapters.remove_label(issue_number, label)

    def ensure_label_exists(self, label: str, *, color: str | None = None, description: str | None = None) -> bool:
        return self.adapters.ensure_label_exists(label, color=color, description=description)

    def get_issue_assignees(self, issue_number: int):
        return self.adapters.get_issue_assignees(issue_number)

    def request_reviewer_assignment(self, issue_number: int, username: str):
        return self.adapters.request_reviewer_assignment(issue_number, username)

    def get_assignment_failure_comment(self, reviewer: str, attempt):
        return self.adapters.get_assignment_failure_comment(reviewer, attempt)

    def add_reaction(self, comment_id: int, reaction: str) -> bool:
        return self.adapters.add_reaction(comment_id, reaction)

    def remove_assignee(self, issue_number: int, username: str) -> bool:
        return self.adapters.remove_assignee(issue_number, username)

    def remove_pr_reviewer(self, issue_number: int, username: str) -> bool:
        return self.adapters.remove_pr_reviewer(issue_number, username)

    def unassign_reviewer(self, issue_number: int, username: str) -> bool:
        return self.adapters.unassign_reviewer(issue_number, username)

    def get_user_permission_status(self, username: str, required_permission: str = "triage") -> str:
        return self.adapters.get_user_permission_status(username, required_permission)

    def check_user_permission(self, username: str, required_permission: str = "triage"):
        return self.adapters.check_user_permission(username, required_permission)

    def get_issue_or_pr_snapshot(self, issue_number: int):
        return self.adapters.get_issue_or_pr_snapshot(issue_number)

    def get_pull_request_reviews(self, issue_number: int):
        return self.adapters.get_pull_request_reviews(issue_number)

    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict):
        return self.adapters.maybe_record_head_observation_repair(issue_number, review_data)

    def handle_transition_notice(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return self.adapters.handle_transition_notice(state, issue_number, reviewer)

    def handle_pass_command(self, state: dict, issue_number: int, comment_author: str, reason: str | None, request=None):
        return self.adapters.handle_pass_command(state, issue_number, comment_author, reason, request=request)

    def handle_pass_until_command(
        self,
        state: dict,
        issue_number: int,
        comment_author: str,
        return_date: str,
        reason: str | None,
        request=None,
    ):
        return self.adapters.handle_pass_until_command(
            state,
            issue_number,
            comment_author,
            return_date,
            reason,
            request=request,
        )

    def handle_label_command(self, state: dict, issue_number: int, label_string: str, request=None):
        return self.adapters.handle_label_command(state, issue_number, label_string, request=request)

    def handle_sync_members_command(self, state: dict):
        return self.adapters.handle_sync_members_command(state)

    def handle_queue_command(self, state: dict):
        return self.adapters.handle_queue_command(state)

    def handle_commands_command(self):
        return self.adapters.handle_commands_command()

    def handle_claim_command(self, state: dict, issue_number: int, comment_author: str, request=None):
        return self.adapters.handle_claim_command(state, issue_number, comment_author, request=request)

    def handle_release_command(self, state: dict, issue_number: int, comment_author: str, args=None, request=None):
        return self.adapters.handle_release_command(state, issue_number, comment_author, args, request=request)

    def handle_rectify_command(self, state: dict, issue_number: int, comment_author: str):
        return self.adapters.handle_rectify_command(state, issue_number, comment_author)

    def handle_assign_command(self, state: dict, issue_number: int, username: str, request=None):
        return self.adapters.handle_assign_command(state, issue_number, username, request=request)

    def handle_assign_from_queue_command(self, state: dict, issue_number: int, request=None):
        return self.adapters.handle_assign_from_queue_command(state, issue_number, request=request)

    def handle_accept_no_fls_changes_command(self, issue_number: int, comment_author: str, request=None):
        return self.adapters.handle_accept_no_fls_changes_command(issue_number, comment_author, request=request)

    def get_commands_help(self) -> str:
        return self.adapters.get_commands_help()

    # Adapter-only mutable review-state compatibility surface.
    # Ownership lives in review_state.py; these methods remain so runtime-oriented
    # callers and test doubles can delegate through one adapter seam.
    def ensure_review_entry(self, state: dict, issue_number: int, create: bool = False):
        return self.adapters.ensure_review_entry(state, issue_number, create=create)

    def set_current_reviewer(self, state: dict, issue_number: int, reviewer: str, assignment_method: str = "round-robin") -> None:
        return self.adapters.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)

    def update_reviewer_activity(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return self.adapters.update_reviewer_activity(state, issue_number, reviewer)

    def mark_review_complete(self, state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
        return self.adapters.mark_review_complete(state, issue_number, reviewer, source)

    def is_triage_or_higher(self, username: str) -> bool:
        return self.adapters.is_triage_or_higher(username)

    def trigger_mandatory_approver_escalation(self, state: dict, issue_number: int) -> bool:
        return self.adapters.trigger_mandatory_approver_escalation(state, issue_number)

    def satisfy_mandatory_approver_requirement(self, state: dict, issue_number: int, approver: str) -> bool:
        return self.adapters.satisfy_mandatory_approver_requirement(state, issue_number, approver)

    def get_next_reviewer(self, state: dict, skip_usernames=None):
        return self.adapters.get_next_reviewer(state, skip_usernames)

    def strip_code_blocks(self, comment_body: str) -> str:
        return self.adapters.strip_code_blocks(comment_body)

    def parse_command(self, comment_body: str):
        return self.adapters.parse_command(comment_body)

    def record_assignment(self, state: dict, github: str, issue_number: int, kind: str) -> None:
        return self.adapters.record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state: dict, username: str) -> bool:
        return self.adapters.reposition_member_as_next(state, username)

    def parse_iso8601_timestamp(self, value: Any):
        return self.adapters.parse_iso8601_timestamp(value)

    def compute_reviewer_response_state(self, issue_number: int, review_data: dict, *, issue_snapshot=None):
        return self.adapters.compute_reviewer_response_state(issue_number, review_data, issue_snapshot=issue_snapshot)

    def run_command(self, command, cwd, check=False):
        return self.adapters.run_command(command, cwd, check)

    def summarize_output(self, result, limit: int = 20) -> str:
        return self.adapters.summarize_output(result, limit)

    def list_changed_files(self, repo_root):
        return self.adapters.list_changed_files(repo_root)

    def get_default_branch(self) -> str:
        return self.adapters.get_default_branch()

    def find_open_pr_for_branch_status(self, branch: str):
        return self.adapters.find_open_pr_for_branch_status(branch)

    def create_pull_request(self, branch: str, base: str, issue_number: int):
        return self.adapters.create_pull_request(branch, base, issue_number)

    def parse_issue_labels(self) -> list[str]:
        return self.adapters.parse_issue_labels()

    def normalize_lock_metadata(self, lock_meta: dict | None):
        return self.adapters.normalize_lock_metadata(lock_meta)

    def get_state_issue(self):
        return self.adapters.get_state_issue()

    def clear_lock_metadata(self):
        return self.adapters.clear_lock_metadata()

    def get_state_issue_snapshot(self):
        return self.adapters.get_state_issue_snapshot()

    def conditional_patch_state_issue(self, body: str, etag: str | None = None):
        return self.adapters.conditional_patch_state_issue(body, etag)

    def parse_lock_metadata_from_issue_body(self, body: str):
        return self.adapters.parse_lock_metadata_from_issue_body(body)

    def render_state_issue_body(self, state: dict, lock_meta: dict, base_body: str | None = None, *, preserve_state_block: bool = False):
        return self.adapters.render_state_issue_body(
            state,
            lock_meta,
            base_body,
            preserve_state_block=preserve_state_block,
        )

    def get_state_issue_html_url(self):
        return self.adapters.get_state_issue_html_url()

    def get_lock_ref_display(self):
        return self.adapters.get_lock_ref_display()

    def get_lock_ref_snapshot(self):
        return self.adapters.get_lock_ref_snapshot()

    def build_lock_metadata(self, *args, **kwargs):
        return self.adapters.build_lock_metadata(*args, **kwargs)

    def create_lock_commit(self, parent_sha: str, tree_sha: str, lock_meta: dict):
        return self.adapters.create_lock_commit(parent_sha, tree_sha, lock_meta)

    def cas_update_lock_ref(self, new_sha: str):
        return self.adapters.cas_update_lock_ref(new_sha)

    def lock_is_currently_valid(self, lock_meta: dict, now: datetime | None = None):
        return self.adapters.lock_is_currently_valid(lock_meta, now)

    def renew_state_issue_lease_lock(self, context):
        result = self.adapters.renew_state_issue_lease_lock(context)
        self.ACTIVE_LEASE_CONTEXT = self.adapters.get_active_lease_context()
        return result

    def ensure_state_issue_lease_lock_fresh(self) -> bool:
        return self.adapters.ensure_state_issue_lease_lock_fresh()

    def acquire_state_issue_lease_lock(self):
        context = self.adapters.acquire_state_issue_lease_lock()
        self.ACTIVE_LEASE_CONTEXT = self.adapters.get_active_lease_context()
        return context

    def release_state_issue_lease_lock(self) -> bool:
        result = self.adapters.release_state_issue_lease_lock()
        self.ACTIVE_LEASE_CONTEXT = self.adapters.get_active_lease_context()
        return result

    def process_pass_until_expirations(self, state: dict):
        return self.adapters.process_pass_until_expirations(state)

    def sync_members_with_queue(self, state: dict):
        return self.adapters.sync_members_with_queue(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self.adapters.sync_status_labels_for_items(state, issue_numbers)
