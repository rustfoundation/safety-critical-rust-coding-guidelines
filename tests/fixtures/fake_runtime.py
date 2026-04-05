from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from scripts.reviewer_bot_lib import automation as automation_module
from scripts.reviewer_bot_lib import commands as commands_module
from scripts.reviewer_bot_lib import comment_routing as comment_routing_module
from scripts.reviewer_bot_lib import config as config_module
from scripts.reviewer_bot_lib import github_api as github_api_module
from scripts.reviewer_bot_lib import lease_lock as lease_lock_module
from scripts.reviewer_bot_lib import lifecycle as lifecycle_module
from scripts.reviewer_bot_lib import maintenance as maintenance_module
from scripts.reviewer_bot_lib import queue as queue_module
from scripts.reviewer_bot_lib import reconcile as reconcile_module
from scripts.reviewer_bot_lib import review_state as review_state_module
from scripts.reviewer_bot_lib import reviews as reviews_module
from scripts.reviewer_bot_lib import state_store as state_store_module
from scripts.reviewer_bot_lib.config import (
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
    BOT_MENTION,
    BOT_NAME,
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS,
    DEFERRED_DISCOVERY_OVERLAP_SECONDS,
    EVENT_INTENT_MUTATING,
    EVENT_INTENT_NON_MUTATING_DEFER,
    EVENT_INTENT_NON_MUTATING_READONLY,
    FLS_AUDIT_LABEL,
    REVIEW_FRESHNESS_RUNBOOK_PATH,
    REVIEWER_REQUEST_422_TEMPLATE,
    STATUS_PROJECTION_EPOCH,
    TRANSITION_PERIOD_DAYS,
    AssignmentAttempt,
    GitHubApiResult,
)
from scripts.reviewer_bot_lib.context import LeaseContext
from tests.fixtures.focused_fake_services import (
    ArtifactDownloadTransportStub,
    ConfigBag,
    DeferredPayloadStore,
    GitHubStub,
    GraphQLTransportStub,
    HandlerStub,
    LockStub,
    OutputCapture,
    RestTransportStub,
    StateStoreStub,
    TouchTrackerStub,
    WorkflowBehaviorStub,
)
from tests.fixtures.recording_logger import RecordingLogger


class FakeRuntimeInfraServices:
    def __init__(self, *, config, outputs, deferred_payloads, logger, rest_transport, graphql_transport, artifact_download_transport, touch_tracker):
        self.config = config
        self.outputs = outputs
        self.deferred_payloads = deferred_payloads
        self.logger = logger
        self.rest_transport = rest_transport
        self.graphql_transport = graphql_transport
        self.artifact_download_transport = artifact_download_transport
        self.touch_tracker = touch_tracker


class FakeRuntimeDomainServices:
    def __init__(self, *, state_store, github, locks, handlers, workflow, adapters, compat):
        self.state_store = state_store
        self.github = github
        self.locks = locks
        self.handlers = handlers
        self.workflow = workflow
        self.adapters = adapters
        self.compat = compat


class FakeRuntimeAdapterServices:
    def __init__(self, runtime: "FakeReviewerBotRuntime"):
        self._runtime = runtime
        self.workflow = runtime.workflow

    def process_pass_until_expirations(self, state: dict):
        return self._runtime.workflow.process_pass_until_expirations(state)

    def sync_members_with_queue(self, state: dict):
        return self._runtime.workflow.sync_members_with_queue(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self._runtime.workflow.sync_status_labels_for_items(state, issue_numbers)


class FakeRuntimeGitHubCompatibility:
    def __init__(self, runtime: "FakeReviewerBotRuntime"):
        self._runtime = runtime

    def get_issue_assignees(self, issue_number: int):
        return github_api_module.get_issue_assignees(self._runtime, issue_number)

    def request_reviewer_assignment(self, issue_number: int, username: str):
        return github_api_module.request_reviewer_assignment(self._runtime, issue_number, username)

    def get_assignment_failure_comment(self, reviewer: str, attempt):
        return github_api_module.get_assignment_failure_comment(self._runtime, reviewer, attempt)

    def post_comment(self, issue_number: int, body: str) -> bool:
        return github_api_module.post_comment(self._runtime, issue_number, body)

    def add_reaction(self, comment_id: int, reaction: str) -> bool:
        return github_api_module.add_reaction(self._runtime, comment_id, reaction)

    def get_user_permission_status(self, username: str, required_permission: str = "triage") -> str:
        return github_api_module.get_user_permission_status(self._runtime, username, required_permission)

    def check_user_permission(self, username: str, required_permission: str = "triage"):
        return github_api_module.check_user_permission(self._runtime, username, required_permission)

    def get_repo_labels(self):
        return github_api_module.get_repo_labels(self._runtime)

    def add_label(self, issue_number: int, label: str) -> bool:
        return github_api_module.add_label(self._runtime, issue_number, label)

    def remove_label(self, issue_number: int, label: str) -> bool:
        return github_api_module.remove_label(self._runtime, issue_number, label)

    def remove_assignee(self, issue_number: int, username: str) -> bool:
        return github_api_module.remove_assignee(self._runtime, issue_number, username)

    def remove_pr_reviewer(self, issue_number: int, username: str) -> bool:
        return github_api_module.remove_pr_reviewer(self._runtime, issue_number, username)

    def unassign_reviewer(self, issue_number: int, username: str) -> bool:
        return github_api_module.unassign_reviewer(self._runtime, issue_number, username)

    def get_issue_or_pr_snapshot(self, issue_number: int) -> dict | None:
        payload = self._runtime.github_api("GET", f"issues/{issue_number}")
        return payload if isinstance(payload, dict) else None

    def get_pull_request_reviews(self, issue_number: int):
        return reviews_module.get_pull_request_reviews(self._runtime, issue_number)

    def github_graphql(self, query: str, variables=None, *, token=None):
        return github_api_module.github_graphql(self._runtime, query, variables, token=token)

    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str:
        if prefer_board_token:
            token = self._runtime.get_config_value("REVIEWER_BOARD_TOKEN")
            if token:
                return token
        token = self._runtime.get_config_value("GITHUB_GRAPHQL_TOKEN") or self._runtime.get_config_value("GITHUB_TOKEN")
        if token:
            return token
        raise RuntimeError("REVIEWER_BOARD_TOKEN not set")


class FakeRuntimeReviewCompatibility:
    def __init__(self, runtime: "FakeReviewerBotRuntime"):
        self._runtime = runtime

    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict):
        return lifecycle_module.maybe_record_head_observation_repair(self._runtime, issue_number, review_data)

    def handle_transition_notice(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return lifecycle_module.handle_transition_notice(self._runtime, state, issue_number, reviewer)

    def ensure_review_entry(self, state: dict, issue_number: int, create: bool = False):
        return review_state_module.ensure_review_entry(state, issue_number, create=create)

    def set_current_reviewer(self, state: dict, issue_number: int, reviewer: str, assignment_method: str | None = None) -> None:
        return review_state_module.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)

    def mark_review_complete(self, state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
        return review_state_module.mark_review_complete(state, issue_number, reviewer, source)

    def update_reviewer_activity(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return review_state_module.update_reviewer_activity(state, issue_number, reviewer)

    def list_open_items_with_status_labels(self) -> list[int]:
        return reviews_module.list_open_items_with_status_labels(self._runtime)

    def handle_pass_command(self, state: dict, issue_number: int, comment_author: str, reason: str | None, request=None):
        return commands_module.handle_pass_command(self._runtime, state, issue_number, comment_author, reason, request=request)

    def handle_pass_until_command(self, state: dict, issue_number: int, comment_author: str, return_date: str, reason: str | None, request=None):
        return commands_module.handle_pass_until_command(self._runtime, state, issue_number, comment_author, return_date, reason, request=request)

    def handle_label_command(self, state: dict, issue_number: int, label_string: str, request=None):
        return commands_module.handle_label_command(self._runtime, state, issue_number, label_string, request=request)

    def handle_sync_members_command(self, state: dict):
        return commands_module.handle_sync_members_command(self._runtime, state)

    def handle_queue_command(self, state: dict):
        return commands_module.handle_queue_command(self._runtime, state)

    def handle_commands_command(self):
        return commands_module.handle_commands_command(self._runtime)

    def handle_claim_command(self, state: dict, issue_number: int, comment_author: str, request=None):
        return commands_module.handle_claim_command(self._runtime, state, issue_number, comment_author, request=request)

    def handle_release_command(self, state: dict, issue_number: int, comment_author: str, args=None, request=None):
        return commands_module.handle_release_command(self._runtime, state, issue_number, comment_author, args, request=request)

    def handle_assign_command(self, state: dict, issue_number: int, username: str, request=None):
        return commands_module.handle_assign_command(self._runtime, state, issue_number, username, request=request)

    def handle_assign_from_queue_command(self, state: dict, issue_number: int, request=None):
        return commands_module.handle_assign_from_queue_command(self._runtime, state, issue_number, request=request)

    def handle_rectify_command(self, state: dict, issue_number: int, comment_author: str):
        return reconcile_module.handle_rectify_command(self._runtime, state, issue_number, comment_author)

    def get_commands_help(self) -> str:
        return config_module.get_commands_help()

    def get_next_reviewer(self, state: dict, skip_usernames=None):
        return queue_module.get_next_reviewer(state, skip_usernames)

    def strip_code_blocks(self, comment_body: str) -> str:
        return commands_module.strip_code_blocks(comment_body)

    def parse_command(self, comment_body: str):
        return commands_module.parse_command(self._runtime, comment_body)

    def record_assignment(self, state: dict, github: str, issue_number: int, kind: str) -> None:
        return queue_module.record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state: dict, username: str) -> bool:
        return queue_module.reposition_member_as_next(state, username)

    def compute_reviewer_response_state(self, issue_number: int, state: dict, *, issue_snapshot=None):
        return reviews_module.compute_reviewer_response_state(self._runtime, issue_number, state, issue_snapshot=issue_snapshot)


class FakeRuntimeStateLockCompatibility:
    def __init__(self, runtime: "FakeReviewerBotRuntime"):
        self._runtime = runtime

    def parse_iso8601_timestamp(self, value: Any):
        return state_store_module.parse_iso8601_timestamp(value)

    def normalize_lock_metadata(self, lock_meta: dict | None):
        return state_store_module.normalize_lock_metadata(lock_meta)

    def get_state_issue(self):
        return state_store_module.get_state_issue(self._runtime)

    def clear_lock_metadata(self):
        return lease_lock_module.clear_lock_metadata(self._runtime)

    def get_state_issue_snapshot(self):
        return state_store_module.get_state_issue_snapshot(self._runtime)

    def conditional_patch_state_issue(self, body: str, etag: str | None = None):
        return state_store_module.conditional_patch_state_issue(self._runtime, body, etag)

    def parse_lock_metadata_from_issue_body(self, body: str):
        return state_store_module.parse_lock_metadata_from_issue_body(body)

    def render_state_issue_body(self, state: dict, lock_meta: dict, base_body: str | None = None, *, preserve_state_block: bool = False):
        return state_store_module.render_state_issue_body(state, lock_meta, base_body, preserve_state_block=preserve_state_block)

    def get_state_issue_html_url(self):
        return lease_lock_module.get_state_issue_html_url(self._runtime)

    def get_lock_ref_display(self):
        return lease_lock_module.get_lock_ref_display(self._runtime)

    def get_lock_ref_snapshot(self):
        return lease_lock_module.get_lock_ref_snapshot(self._runtime)

    def build_lock_metadata(self, *args, **kwargs):
        return lease_lock_module.build_lock_metadata(self._runtime, *args, **kwargs)

    def create_lock_commit(self, parent_sha, tree_sha, lock_meta):
        return lease_lock_module.create_lock_commit(self._runtime, parent_sha, tree_sha, lock_meta)

    def cas_update_lock_ref(self, new_sha):
        return lease_lock_module.cas_update_lock_ref(self._runtime, new_sha)

    def lock_is_currently_valid(self, lock_meta: dict, now=None):
        return lease_lock_module.lock_is_currently_valid(self._runtime, lock_meta, now)

    def renew_state_issue_lease_lock(self, context):
        return lease_lock_module.renew_state_issue_lease_lock(self._runtime, context)

    def ensure_state_issue_lease_lock_fresh(self):
        return self._runtime.locks.refresh()

    def acquire_state_issue_lease_lock(self):
        return self._runtime.locks.acquire()

    def release_state_issue_lease_lock(self):
        return self._runtime.locks.release()


class FakeRuntimeAutomationCompatibility:
    def __init__(self, runtime: "FakeReviewerBotRuntime"):
        self._runtime = runtime

    def run_command(self, command, cwd, check=False):
        return automation_module.run_command(command, cwd=cwd, check=check)

    def summarize_output(self, result, limit: int = 20) -> str:
        return automation_module.summarize_output(result, limit=limit)

    def list_changed_files(self, repo_root):
        return automation_module.list_changed_files(repo_root)

    def get_default_branch(self) -> str:
        return automation_module.get_default_branch(self._runtime)

    def find_open_pr_for_branch_status(self, branch: str):
        return automation_module.find_open_pr_for_branch_status(self._runtime, branch)

    def create_pull_request(self, branch: str, base: str, issue_number: int):
        return automation_module.create_pull_request(self._runtime, branch, base, issue_number)

    def parse_issue_labels(self) -> list[str]:
        return automation_module.bot_parse_issue_labels(self._runtime)

    def fetch_members(self):
        return self._runtime._fetch_members()

    def handle_accept_no_fls_changes_command(self, issue_number: int, comment_author: str, request=None):
        return automation_module.handle_accept_no_fls_changes_command(self._runtime, issue_number, comment_author, request=request)


class FakeReviewerBotRuntime:
    BOT_NAME = BOT_NAME
    BOT_MENTION = BOT_MENTION
    FLS_AUDIT_LABEL = FLS_AUDIT_LABEL
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST = AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
    REVIEWER_REQUEST_422_TEMPLATE = REVIEWER_REQUEST_422_TEMPLATE
    REVIEW_FRESHNESS_RUNBOOK_PATH = REVIEW_FRESHNESS_RUNBOOK_PATH
    REVIEW_DEADLINE_DAYS = 14
    TRANSITION_PERIOD_DAYS = TRANSITION_PERIOD_DAYS
    DEFERRED_DISCOVERY_OVERLAP_SECONDS = DEFERRED_DISCOVERY_OVERLAP_SECONDS
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS = DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS
    GitHubApiResult = GitHubApiResult
    AssignmentAttempt = AssignmentAttempt
    EVENT_INTENT_MUTATING = EVENT_INTENT_MUTATING
    EVENT_INTENT_NON_MUTATING_DEFER = EVENT_INTENT_NON_MUTATING_DEFER
    EVENT_INTENT_NON_MUTATING_READONLY = EVENT_INTENT_NON_MUTATING_READONLY
    STATUS_PROJECTION_EPOCH = STATUS_PROJECTION_EPOCH
    datetime = datetime
    timezone = timezone

    def __init__(self, monkeypatch, *, github=None):
        self.sys = sys
        self.random = random
        self.time = time
        self.logger = RecordingLogger()
        self.ACTIVE_LEASE_CONTEXT = LeaseContext(
            lock_token="test-lock-token",
            lock_owner_run_id="test-run",
            lock_owner_workflow="test-workflow",
            lock_owner_job="test-job",
            state_issue_url="https://example.com/state",
        )
        self.config = ConfigBag(monkeypatch)
        self.outputs = OutputCapture()
        self.deferred_payloads = DeferredPayloadStore()
        self.github = GitHubStub(github)
        self.rest_transport = RestTransportStub(self.github)
        self.graphql_transport = GraphQLTransportStub()
        self.artifact_download_transport = ArtifactDownloadTransportStub()
        self.touch_tracker = TouchTrackerStub()
        self.state_store = StateStoreStub()
        self.locks = LockStub()
        self.workflow = WorkflowBehaviorStub()
        self._fetch_members = lambda: []
        self.adapters = FakeRuntimeAdapterServices(self)
        self.compat = SimpleNamespace(
            github=FakeRuntimeGitHubCompatibility(self),
            review=FakeRuntimeReviewCompatibility(self),
            state_lock=FakeRuntimeStateLockCompatibility(self),
            automation=FakeRuntimeAutomationCompatibility(self),
        )
        self.handlers = HandlerStub(
            {
                "handle_issue_or_pr_opened": lambda state: lifecycle_module.handle_issue_or_pr_opened(self, state),
                "handle_labeled_event": lambda state: lifecycle_module.handle_labeled_event(self, state),
                "handle_issue_edited_event": lambda state: lifecycle_module.handle_issue_edited_event(self, state),
                "handle_closed_event": lambda state: lifecycle_module.handle_closed_event(self, state),
                "handle_pull_request_target_synchronize": lambda state: lifecycle_module.handle_pull_request_target_synchronize(self, state),
                "handle_pull_request_review_event": lambda state: lifecycle_module.handle_pull_request_review_event(self, state),
                "handle_comment_event": lambda state: comment_routing_module.handle_comment_event(self, state),
                "handle_manual_dispatch": lambda state: maintenance_module.handle_manual_dispatch(self, state),
                "handle_scheduled_check": lambda state: maintenance_module.handle_scheduled_check(self, state),
                "handle_workflow_run_event": lambda state: reconcile_module.handle_workflow_run_event(self, state),
            }
        )
        self.infra = FakeRuntimeInfraServices(
            config=self.config,
            outputs=self.outputs,
            deferred_payloads=self.deferred_payloads,
            logger=self.logger,
            rest_transport=self.rest_transport,
            graphql_transport=self.graphql_transport,
            artifact_download_transport=self.artifact_download_transport,
            touch_tracker=self.touch_tracker,
        )
        self.domain = FakeRuntimeDomainServices(
            state_store=self.state_store,
            github=self.github,
            locks=self.locks,
            handlers=self.handlers,
            workflow=self.workflow,
            adapters=self.adapters,
            compat=self.compat,
        )

    def get_config_value(self, name: str, default: str = "") -> str:
        return self.config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self.config.set(name, value)

    def get_github_token(self) -> str:
        token = self.get_config_value("GITHUB_TOKEN")
        if not token:
            raise SystemExit(1)
        return token

    def state_issue_number(self) -> int:
        return int(self.get_config_value("STATE_ISSUE_NUMBER", "0") or 0)

    def lock_api_retry_limit(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_API_RETRY_LIMIT", "5") or 0)

    def lock_retry_base_seconds(self) -> float:
        return float(self.get_config_value("REVIEWER_BOT_LOCK_RETRY_SECONDS", "2.0") or 0.0)

    def lock_lease_ttl_seconds(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_TTL_SECONDS", "300") or 0)

    def lock_max_wait_seconds(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_MAX_WAIT_SECONDS", "120") or 0)

    def lock_renewal_window_seconds(self) -> int:
        return int(self.get_config_value("REVIEWER_BOT_LOCK_RENEWAL_WINDOW_SECONDS", "60") or 0)

    def lock_ref_name(self) -> str:
        return self.get_config_value("REVIEWER_BOT_LOCK_REF_NAME", "refs/heads/reviewer-bot-lock")

    def lock_ref_bootstrap_branch(self) -> str:
        return self.get_config_value("REVIEWER_BOT_LOCK_BOOTSTRAP_BRANCH", "main")

    def write_output(self, name: str, value: str) -> None:
        self.outputs.write(name, value)

    def assert_lock_held(self, _context: str) -> None:
        return None

    def load_deferred_payload(self) -> dict:
        return self.deferred_payloads.load()

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self.state_store.load_state(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self.state_store.save_state(state)

    def ensure_state_issue_lease_lock_fresh(self) -> bool:
        return self.compat.state_lock.ensure_state_issue_lease_lock_fresh()

    def acquire_state_issue_lease_lock(self):
        return self.compat.state_lock.acquire_state_issue_lease_lock()

    def release_state_issue_lease_lock(self) -> bool:
        return self.compat.state_lock.release_state_issue_lease_lock()

    def process_pass_until_expirations(self, state: dict):
        return self.workflow.process_pass_until_expirations(state)

    def sync_members_with_queue(self, state: dict):
        return self.workflow.sync_members_with_queue(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self.workflow.sync_status_labels_for_items(state, issue_numbers)

    def ensure_review_entry(self, state: dict, issue_number: int, create: bool = False):
        return review_state_module.ensure_review_entry(state, issue_number, create=create)

    def get_issue_assignees(self, issue_number: int):
        return self.compat.github.get_issue_assignees(issue_number)

    def request_reviewer_assignment(self, issue_number: int, username: str):
        return self.compat.github.request_reviewer_assignment(issue_number, username)

    def get_assignment_failure_comment(self, reviewer: str, attempt):
        return self.compat.github.get_assignment_failure_comment(reviewer, attempt)

    def post_comment(self, issue_number: int, body: str) -> bool:
        return self.compat.github.post_comment(issue_number, body)

    def add_reaction(self, comment_id: int, reaction: str) -> bool:
        return self.compat.github.add_reaction(comment_id, reaction)

    def get_user_permission_status(self, username: str, required_permission: str = "triage") -> str:
        return self.compat.github.get_user_permission_status(username, required_permission)

    def check_user_permission(self, username: str, required_permission: str = "triage"):
        return self.compat.github.check_user_permission(username, required_permission)

    def get_repo_labels(self):
        return self.compat.github.get_repo_labels()

    def add_label(self, issue_number: int, label: str) -> bool:
        return self.compat.github.add_label(issue_number, label)

    def remove_label(self, issue_number: int, label: str) -> bool:
        return self.compat.github.remove_label(issue_number, label)

    def remove_assignee(self, issue_number: int, username: str) -> bool:
        return self.compat.github.remove_assignee(issue_number, username)

    def remove_pr_reviewer(self, issue_number: int, username: str) -> bool:
        return self.compat.github.remove_pr_reviewer(issue_number, username)

    def unassign_reviewer(self, issue_number: int, username: str) -> bool:
        return self.compat.github.unassign_reviewer(issue_number, username)

    def get_issue_or_pr_snapshot(self, issue_number: int) -> dict | None:
        return self.compat.github.get_issue_or_pr_snapshot(issue_number)

    def get_pull_request_reviews(self, issue_number: int):
        return self.compat.github.get_pull_request_reviews(issue_number)

    def list_open_items_with_status_labels(self) -> list[int]:
        return self.compat.review.list_open_items_with_status_labels()

    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict):
        return self.compat.review.maybe_record_head_observation_repair(issue_number, review_data)

    def set_current_reviewer(self, state: dict, issue_number: int, reviewer: str, assignment_method: str | None = None) -> None:
        return self.compat.review.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)

    def mark_review_complete(self, state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
        return self.compat.review.mark_review_complete(state, issue_number, reviewer, source)

    def update_reviewer_activity(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return self.compat.review.update_reviewer_activity(state, issue_number, reviewer)

    def accept_reviewer_review_from_live_review(self, review_data: dict, review: dict, *, actor: str | None = None) -> bool:
        return review_state_module.accept_reviewer_review_from_live_review(review_data, review, actor=actor)

    def refresh_reviewer_review_from_live_preferred_review(self, issue_number: int, review_data: dict, *, pull_request=None, reviews=None, actor: str | None = None):
        return review_state_module.refresh_reviewer_review_from_live_preferred_review(
            self,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
            actor=actor,
        )

    def repair_missing_reviewer_review_state(self, issue_number: int, review_data: dict, *, reviews=None) -> bool:
        return review_state_module.repair_missing_reviewer_review_state(self, issue_number, review_data, reviews=reviews)

    def list_open_tracked_review_items(self, state: dict) -> list[int]:
        return review_state_module.list_open_tracked_review_items(state)

    def semantic_key_seen(self, review_data: dict, channel_name: str, semantic_key: str) -> bool:
        return review_state_module.semantic_key_seen(review_data, channel_name, semantic_key)

    def get_next_reviewer(self, state: dict, skip_usernames=None):
        return self.compat.review.get_next_reviewer(state, skip_usernames)

    def strip_code_blocks(self, comment_body: str) -> str:
        return self.compat.review.strip_code_blocks(comment_body)

    def parse_command(self, comment_body: str):
        return self.compat.review.parse_command(comment_body)

    def record_assignment(self, state: dict, github: str, issue_number: int, kind: str) -> None:
        return self.compat.review.record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state: dict, username: str) -> bool:
        return self.compat.review.reposition_member_as_next(state, username)

    def parse_iso8601_timestamp(self, value: Any):
        return self.compat.state_lock.parse_iso8601_timestamp(value)

    def compute_reviewer_response_state(self, issue_number: int, state: dict, *, issue_snapshot=None):
        return self.compat.review.compute_reviewer_response_state(issue_number, state, issue_snapshot=issue_snapshot)

    def rebuild_pr_approval_state(self, *args, pull_request=None, reviews=None):
        if len(args) == 2:
            issue_number, review_data = args
        elif len(args) == 3:
            _bot, issue_number, review_data = args
        else:
            raise TypeError("unexpected rebuild_pr_approval_state args")
        return reviews_module.rebuild_pr_approval_state(
            self,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )

    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str:
        return self.compat.github.get_github_graphql_token(prefer_board_token=prefer_board_token)

    def github_graphql(self, query: str, variables=None, *, token=None):
        return self.compat.github.github_graphql(query, variables, token=token)

    def handle_transition_notice(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return self.compat.review.handle_transition_notice(state, issue_number, reviewer)

    def handle_pass_command(self, state: dict, issue_number: int, comment_author: str, reason: str | None, request=None):
        return self.compat.review.handle_pass_command(state, issue_number, comment_author, reason, request=request)

    def handle_pass_until_command(self, state: dict, issue_number: int, comment_author: str, return_date: str, reason: str | None, request=None):
        return self.compat.review.handle_pass_until_command(state, issue_number, comment_author, return_date, reason, request=request)

    def handle_label_command(self, state: dict, issue_number: int, label_string: str, request=None):
        return self.compat.review.handle_label_command(state, issue_number, label_string, request=request)

    def handle_sync_members_command(self, state: dict):
        return self.compat.review.handle_sync_members_command(state)

    def handle_queue_command(self, state: dict):
        return self.compat.review.handle_queue_command(state)

    def handle_commands_command(self):
        return self.compat.review.handle_commands_command()

    def handle_claim_command(self, state: dict, issue_number: int, comment_author: str, request=None):
        return self.compat.review.handle_claim_command(state, issue_number, comment_author, request=request)

    def handle_release_command(self, state: dict, issue_number: int, comment_author: str, args=None, request=None):
        return self.compat.review.handle_release_command(state, issue_number, comment_author, args, request=request)

    def handle_assign_command(self, state: dict, issue_number: int, username: str, request=None):
        return self.compat.review.handle_assign_command(state, issue_number, username, request=request)

    def handle_assign_from_queue_command(self, state: dict, issue_number: int, request=None):
        return self.compat.review.handle_assign_from_queue_command(state, issue_number, request=request)

    def handle_accept_no_fls_changes_command(self, issue_number: int, comment_author: str, request=None):
        return self.compat.automation.handle_accept_no_fls_changes_command(issue_number, comment_author, request=request)

    def handle_rectify_command(self, state: dict, issue_number: int, comment_author: str):
        return self.compat.review.handle_rectify_command(state, issue_number, comment_author)

    def get_commands_help(self) -> str:
        return self.compat.review.get_commands_help()

    def parse_issue_labels(self) -> list[str]:
        return self.compat.automation.parse_issue_labels()

    def fetch_members(self):
        return self.compat.automation.fetch_members()

    def run_command(self, command, cwd, check=False):
        return self.compat.automation.run_command(command, cwd, check=check)

    def summarize_output(self, result, limit: int = 20) -> str:
        return self.compat.automation.summarize_output(result, limit=limit)

    def list_changed_files(self, repo_root):
        return self.compat.automation.list_changed_files(repo_root)

    def get_default_branch(self) -> str:
        return self.compat.automation.get_default_branch()

    def find_open_pr_for_branch_status(self, branch: str):
        return self.compat.automation.find_open_pr_for_branch_status(branch)

    def create_pull_request(self, branch: str, base: str, issue_number: int):
        return self.compat.automation.create_pull_request(branch, base, issue_number)

    def handle_issue_or_pr_opened(self, state: dict) -> bool:
        return self.handlers.call("handle_issue_or_pr_opened", state)

    def handle_labeled_event(self, state: dict) -> bool:
        return self.handlers.call("handle_labeled_event", state)

    def handle_issue_edited_event(self, state: dict) -> bool:
        return self.handlers.call("handle_issue_edited_event", state)

    def handle_closed_event(self, state: dict) -> bool:
        return self.handlers.call("handle_closed_event", state)

    def handle_pull_request_target_synchronize(self, state: dict) -> bool:
        return self.handlers.call("handle_pull_request_target_synchronize", state)

    def handle_pull_request_review_event(self, state: dict) -> bool:
        return self.handlers.call("handle_pull_request_review_event", state)

    def handle_comment_event(self, state: dict) -> bool:
        return self.handlers.call("handle_comment_event", state)

    def handle_manual_dispatch(self, state: dict) -> bool:
        return self.handlers.call("handle_manual_dispatch", state)

    def handle_scheduled_check(self, state: dict) -> bool:
        return self.handlers.call("handle_scheduled_check", state)

    def handle_workflow_run_event(self, state: dict) -> bool:
        return self.handlers.call("handle_workflow_run_event", state)

    def github_api(self, method: str, endpoint: str, data=None):
        return self.github.github_api(method, endpoint, data=data)

    def github_api_request(self, method: str, endpoint: str, data=None, extra_headers=None, **kwargs):
        return self.github.github_api_request(
            method,
            endpoint,
            data=data,
            extra_headers=extra_headers,
            **kwargs,
        )

    def collect_touched_item(self, issue_number: int) -> None:
        self.touch_tracker.collect(issue_number)

    def drain_touched_items(self) -> list[int]:
        return self.touch_tracker.drain()

    def stub_lock(self, *, acquire=None, release=None, refresh=None) -> None:
        self.locks.stub(acquire=acquire, release=release, refresh=refresh)

    def stub_deferred_payload(self, payload: dict) -> None:
        self.deferred_payloads.set_payload(payload)

    def stub_state_sequence(self, *states: dict) -> None:
        self.state_store.stub_state_sequence(*states)

    def stub_state_unavailable(self, message: str = "state unavailable") -> None:
        self.state_store.stub_state_unavailable(message)

    def record_saves(self, snapshots: list) -> None:
        self.state_store.record_saves(snapshots)

    def stub_pass_until(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self.workflow.stub_pass_until(func)

    def stub_sync_members(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self.workflow.stub_sync_members(func)

    def stub_sync_status_labels(self, func: Callable[[dict, Any], bool]) -> None:
        self.workflow.stub_sync_status_labels(func)

    def stub_fetch_members(self, func: Callable[[], list[dict]]) -> None:
        self._fetch_members = func
