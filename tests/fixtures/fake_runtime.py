from __future__ import annotations

import json
import random
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from scripts.reviewer_bot_lib import automation as automation_module
from scripts.reviewer_bot_lib import commands as commands_module
from scripts.reviewer_bot_lib import comment_routing as comment_routing_module
from scripts.reviewer_bot_lib import config as config_module
from scripts.reviewer_bot_lib import github_api as github_api_module
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


class ConfigBag:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.values: dict[str, str] = {}

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    def set(self, name: str, value) -> None:
        rendered = str(value)
        self.values[name] = rendered
        self._monkeypatch.setenv(name, rendered)


class OutputCapture:
    def __init__(self):
        self.writes: list[tuple[str, str]] = []

    def write(self, name: str, value: str) -> None:
        self.writes.append((name, value))


class DeferredPayloadStore:
    def __init__(self):
        self._payload: dict = {}

    def set_payload(self, payload: dict) -> None:
        self._payload = payload

    def load(self) -> dict:
        return self._payload


class StateStoreStub:
    def __init__(self):
        self._load: Callable[..., dict] = lambda *, fail_on_unavailable=False: {"active_reviews": {}}
        self._save: Callable[[dict], bool] = lambda state: True

    def stub_load(self, func: Callable[..., dict]) -> None:
        self._load = func

    def stub_save(self, func: Callable[[dict], bool]) -> None:
        self._save = func

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self._load(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self._save(state)


class LockStub:
    def __init__(self):
        self._acquire: Callable[[], Any] = lambda: None
        self._release: Callable[[], bool] = lambda: True
        self._refresh: Callable[[], bool] = lambda: True

    def stub(self, *, acquire=None, release=None, refresh=None) -> None:
        if acquire is not None:
            self._acquire = acquire
        if release is not None:
            self._release = release
        if refresh is not None:
            self._refresh = refresh

    def acquire(self):
        return self._acquire()

    def release(self) -> bool:
        return self._release()

    def refresh(self) -> bool:
        return self._refresh()


class GitHubStub:
    def __init__(self, github=None):
        self._github = github

    def stub(self, github) -> None:
        self._github = github

    def github_api(self, method: str, endpoint: str, data=None):
        if self._github is None:
            raise AssertionError(f"No GitHub stub configured for {method} {endpoint}")
        return self._github.github_api(method, endpoint, data=data)

    def github_api_request(self, method: str, endpoint: str, data=None, extra_headers=None, **kwargs):
        if self._github is None:
            raise AssertionError(f"No GitHub request stub configured for {method} {endpoint}")
        return self._github.github_api_request(
            method,
            endpoint,
            data=data,
            extra_headers=extra_headers,
            **kwargs,
        )


class HandlerStub:
    ALLOWED = {
        "handle_issue_or_pr_opened",
        "handle_labeled_event",
        "handle_issue_edited_event",
        "handle_closed_event",
        "handle_pull_request_target_synchronize",
        "handle_pull_request_review_event",
        "handle_comment_event",
        "handle_manual_dispatch",
        "handle_scheduled_check",
        "handle_workflow_run_event",
    }

    def __init__(self, defaults: dict[str, Callable[[dict], bool]]):
        self._handlers: dict[str, Callable[[dict], bool]] = defaults

    @staticmethod
    def _missing_handler(name: str) -> Callable[[dict], bool]:
        def fail(_state: dict) -> bool:
            raise AssertionError(f"No handler stub configured for {name}")

        return fail

    def stub(self, name: str, func: Callable[[dict], bool]) -> None:
        if name not in self.ALLOWED:
            raise AssertionError(f"Unsupported runtime handler override: {name}")
        self._handlers[name] = func

    def call(self, name: str, state: dict) -> bool:
        return self._handlers[name](state)


class TouchTrackerStub:
    def __init__(self):
        self._touched: list[int] = []

    def collect(self, issue_number: int | None) -> None:
        if isinstance(issue_number, int) and issue_number not in self._touched:
            self._touched.append(issue_number)

    def drain(self) -> list[int]:
        items = list(self._touched)
        self._touched.clear()
        return items


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
        self.state_store = StateStoreStub()
        self.locks = LockStub()
        self.github = GitHubStub(github)
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
        self.touch_tracker = TouchTrackerStub()
        self._process_pass_until: Callable[[dict], tuple[dict, list[str]]] = lambda state: (state, [])
        self._sync_members: Callable[[dict], tuple[dict, list[str]]] = lambda state: (state, [])
        self._sync_status_labels: Callable[[dict, Any], bool] = lambda state, issue_numbers: False

    def get_config_value(self, name: str, default: str = "") -> str:
        return self.config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self.config.set(name, value)

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
        return self.locks.refresh()

    def acquire_state_issue_lease_lock(self):
        return self.locks.acquire()

    def release_state_issue_lease_lock(self) -> bool:
        return self.locks.release()

    def process_pass_until_expirations(self, state: dict):
        return self._process_pass_until(state)

    def sync_members_with_queue(self, state: dict):
        return self._sync_members(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self._sync_status_labels(state, issue_numbers)

    def ensure_review_entry(self, state: dict, issue_number: int, create: bool = False):
        return review_state_module.ensure_review_entry(state, issue_number, create=create)

    def get_issue_assignees(self, issue_number: int):
        return github_api_module.get_issue_assignees(self, issue_number)

    def request_reviewer_assignment(self, issue_number: int, username: str):
        return github_api_module.request_reviewer_assignment(self, issue_number, username)

    def get_assignment_failure_comment(self, reviewer: str, attempt):
        return github_api_module.get_assignment_failure_comment(self, reviewer, attempt)

    def post_comment(self, issue_number: int, body: str) -> bool:
        return github_api_module.post_comment(self, issue_number, body)

    def add_reaction(self, comment_id: int, reaction: str) -> bool:
        return github_api_module.add_reaction(self, comment_id, reaction)

    def get_user_permission_status(self, username: str, required_permission: str = "triage") -> str:
        return github_api_module.get_user_permission_status(self, username, required_permission)

    def check_user_permission(self, username: str, required_permission: str = "triage"):
        return github_api_module.check_user_permission(self, username, required_permission)

    def get_repo_labels(self):
        return github_api_module.get_repo_labels(self)

    def add_label(self, issue_number: int, label: str) -> bool:
        return github_api_module.add_label(self, issue_number, label)

    def remove_label(self, issue_number: int, label: str) -> bool:
        return github_api_module.remove_label(self, issue_number, label)

    def remove_assignee(self, issue_number: int, username: str) -> bool:
        return github_api_module.remove_assignee(self, issue_number, username)

    def remove_pr_reviewer(self, issue_number: int, username: str) -> bool:
        return github_api_module.remove_pr_reviewer(self, issue_number, username)

    def unassign_reviewer(self, issue_number: int, username: str) -> bool:
        return github_api_module.unassign_reviewer(self, issue_number, username)

    def get_issue_or_pr_snapshot(self, issue_number: int) -> dict | None:
        payload = self.github_api("GET", f"issues/{issue_number}")
        return payload if isinstance(payload, dict) else None

    def get_pull_request_reviews(self, issue_number: int):
        return reviews_module.get_pull_request_reviews(self, issue_number)

    def list_open_items_with_status_labels(self) -> list[int]:
        return reviews_module.list_open_items_with_status_labels(self)

    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict):
        return lifecycle_module.maybe_record_head_observation_repair(self, issue_number, review_data)

    def set_current_reviewer(self, state: dict, issue_number: int, reviewer: str, assignment_method: str | None = None) -> None:
        return review_state_module.set_current_reviewer(state, issue_number, reviewer, assignment_method=assignment_method)

    def mark_review_complete(self, state: dict, issue_number: int, reviewer: str | None, source: str) -> bool:
        return review_state_module.mark_review_complete(state, issue_number, reviewer, source)

    def update_reviewer_activity(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return review_state_module.update_reviewer_activity(state, issue_number, reviewer)

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
        return queue_module.get_next_reviewer(state, skip_usernames)

    def strip_code_blocks(self, comment_body: str) -> str:
        return commands_module.strip_code_blocks(comment_body)

    def parse_command(self, comment_body: str):
        return commands_module.parse_command(self, comment_body)

    def record_assignment(self, state: dict, github: str, issue_number: int, kind: str) -> None:
        return queue_module.record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state: dict, username: str) -> bool:
        return queue_module.reposition_member_as_next(state, username)

    def parse_iso8601_timestamp(self, value: Any):
        return state_store_module.parse_iso8601_timestamp(value)

    def compute_reviewer_response_state(self, issue_number: int, state: dict, *, issue_snapshot=None):
        return reviews_module.compute_reviewer_response_state(self, issue_number, state, issue_snapshot=issue_snapshot)

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
        if prefer_board_token:
            token = self.get_config_value("REVIEWER_BOARD_TOKEN")
            if token:
                return token
        token = self.get_config_value("GITHUB_GRAPHQL_TOKEN") or self.get_config_value("GITHUB_TOKEN")
        if token:
            return token
        raise RuntimeError("REVIEWER_BOARD_TOKEN not set")

    def github_graphql(self, query: str, variables=None, *, token=None):
        return github_api_module.github_graphql(self, query, variables, token=token)

    def handle_transition_notice(self, state: dict, issue_number: int, reviewer: str) -> bool:
        return lifecycle_module.handle_transition_notice(self, state, issue_number, reviewer)

    def handle_pass_command(self, state: dict, issue_number: int, comment_author: str, reason: str | None, request=None):
        return commands_module.handle_pass_command(self, state, issue_number, comment_author, reason, request=request)

    def handle_pass_until_command(self, state: dict, issue_number: int, comment_author: str, return_date: str, reason: str | None, request=None):
        return commands_module.handle_pass_until_command(self, state, issue_number, comment_author, return_date, reason, request=request)

    def handle_label_command(self, state: dict, issue_number: int, label_string: str, request=None):
        return commands_module.handle_label_command(self, state, issue_number, label_string, request=request)

    def handle_sync_members_command(self, state: dict):
        return commands_module.handle_sync_members_command(self, state)

    def handle_queue_command(self, state: dict):
        return commands_module.handle_queue_command(self, state)

    def handle_commands_command(self):
        return commands_module.handle_commands_command(self)

    def handle_claim_command(self, state: dict, issue_number: int, comment_author: str, request=None):
        return commands_module.handle_claim_command(self, state, issue_number, comment_author, request=request)

    def handle_release_command(self, state: dict, issue_number: int, comment_author: str, args=None, request=None):
        return commands_module.handle_release_command(self, state, issue_number, comment_author, args, request=request)

    def handle_assign_command(self, state: dict, issue_number: int, username: str, request=None):
        return commands_module.handle_assign_command(self, state, issue_number, username, request=request)

    def handle_assign_from_queue_command(self, state: dict, issue_number: int, request=None):
        return commands_module.handle_assign_from_queue_command(self, state, issue_number, request=request)

    def handle_accept_no_fls_changes_command(self, issue_number: int, comment_author: str, request=None):
        return automation_module.handle_accept_no_fls_changes_command(self, issue_number, comment_author, request=request)

    def handle_rectify_command(self, state: dict, issue_number: int, comment_author: str):
        return reconcile_module.handle_rectify_command(self, state, issue_number, comment_author)

    def get_commands_help(self) -> str:
        return config_module.get_commands_help()

    def parse_issue_labels(self) -> list[str]:
        return automation_module.bot_parse_issue_labels(self)

    def run_command(self, command, cwd, check=False):
        return automation_module.run_command(command, cwd=cwd, check=check)

    def summarize_output(self, result, limit: int = 20) -> str:
        return automation_module.summarize_output(result, limit=limit)

    def list_changed_files(self, repo_root):
        return automation_module.list_changed_files(repo_root)

    def get_default_branch(self) -> str:
        return automation_module.get_default_branch(self)

    def find_open_pr_for_branch_status(self, branch: str):
        return automation_module.find_open_pr_for_branch_status(self, branch)

    def create_pull_request(self, branch: str, base: str, issue_number: int):
        return automation_module.create_pull_request(self, branch, base, issue_number)

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
        state_queue = [deepcopy(state) for state in states]

        def fake_load_state(*, fail_on_unavailable: bool = False):
            if not state_queue:
                raise AssertionError("No more fake states queued")
            if len(state_queue) == 1:
                return state_queue[0]
            return state_queue.pop(0)

        self.state_store.stub_load(fake_load_state)

    def stub_state_unavailable(self, message: str = "state unavailable") -> None:
        def fake_load_state(*, fail_on_unavailable: bool = False):
            assert fail_on_unavailable is True
            raise RuntimeError(message)

        self.state_store.stub_load(fake_load_state)

    def record_saves(self, snapshots: list) -> None:
        def fake_save_state(state: dict) -> bool:
            snapshots.append(json.loads(json.dumps(state)))
            return True

        self.state_store.stub_save(fake_save_state)

    def stub_pass_until(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self._process_pass_until = func

    def stub_sync_members(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self._sync_members = func

    def stub_sync_status_labels(self, func: Callable[[dict, Any], bool]) -> None:
        self._sync_status_labels = func
